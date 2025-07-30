"""OpenShift authentication integration."""

import os
from typing import Any

import httpx
import structlog

from .cache import TokenCache
from .models import User

logger = structlog.get_logger()


class OpenShiftClient:
    """Client for OpenShift API authentication operations."""

    def __init__(
        self,
        api_url: str,
        service_account_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        ca_cert_path: str | None = None,
    ):
        """Initialize OpenShift client.

        Args:
            api_url: OpenShift API server URL
            service_account_token_path: Path to service account token for API calls
            ca_cert_path: Path to CA certificate file for SSL verification
                         (optional, only needed for custom certificates.
                         OpenShift clusters with valid LetsEncrypt certs work
                         with the default system CA bundle)
        """
        self.api_url = api_url.rstrip("/")
        self.service_account_token_path = service_account_token_path
        self.ca_cert_path = ca_cert_path or os.getenv("OPENSHIFT_CA_CERT_PATH")
        self.cache = TokenCache(
            ttl_seconds=int(os.getenv("AUTH_CACHE_TTL_SECONDS", "300"))
        )
        self._service_account_token: str | None = None

    def _get_service_account_token(self) -> str:
        """Get service account token for API calls."""
        if self._service_account_token is None:
            # First try environment variable (for local development)
            env_token = os.getenv("OPENSHIFT_SERVICE_ACCOUNT_TOKEN")
            if env_token:
                self._service_account_token = env_token
                logger.info("Using service account token from environment variable")
                return self._service_account_token

            # Then try service account token file (for pod deployment)
            try:
                with open(self.service_account_token_path) as f:
                    self._service_account_token = f.read().strip()
                    logger.info(
                        "Using service account token from file",
                        path=self.service_account_token_path,
                    )
            except FileNotFoundError:
                logger.warning(
                    "Service account token not found in file or environment, using user token for validation",
                    path=self.service_account_token_path,
                )
                # In development, we might not have a service account token
                # The validation will use the provided token itself
                return ""
        return self._service_account_token or ""

    def _get_ssl_verify_config(self) -> bool | str:
        """Get SSL verification configuration.

        When running within a pod, OpenShift clusters typically have valid
        LetsEncrypt certificates accessible from outside, and the default
        system CA bundle should handle verification correctly.

        Returns:
            - False: Disable SSL verification (insecure, for development only)
            - True: Use system CA bundle (default, works with LetsEncrypt certs)
            - str: Path to custom CA certificate file (only needed for custom certs)
        """
        # If CA cert path is provided and exists, use it (highest priority)
        if self.ca_cert_path and os.path.exists(self.ca_cert_path):
            logger.info("Using custom CA certificate", ca_cert_path=self.ca_cert_path)
            return self.ca_cert_path

        # Check environment variable for SSL verification control
        ssl_verify_env = os.getenv("OPENSHIFT_SSL_VERIFY", "true").lower()

        if ssl_verify_env == "false":
            logger.warning(
                "SSL certificate verification disabled - this is insecure and should only be used for development"
            )
            return False

        # Default to system CA bundle
        return True

    async def validate_token(self, token: str) -> User | None:
        """Validate a bearer token against OpenShift API.

        Args:
            token: Bearer token to validate

        Returns:
            User object if token is valid, None otherwise
        """
        # Check cache first
        cached_user = self.cache.get(token)
        if cached_user:
            return cached_user

        # Validate against OpenShift API
        # Note: Service account token logic available for future use (e.g., impersonation)
        # sa_token = self._get_service_account_token()

        # Configure SSL verification
        ssl_verify = self._get_ssl_verify_config()

        try:
            async with httpx.AsyncClient(timeout=5.0, verify=ssl_verify) as client:
                # Try to get user info using the token
                response = await client.get(
                    f"{self.api_url}/apis/user.openshift.io/v1/users/~",
                    headers={"Authorization": f"Bearer {token}"},
                )

                if response.status_code == 200:
                    user_info = response.json()
                    user = User(
                        username=user_info["metadata"]["name"],
                        uid=user_info["metadata"]["uid"],
                        groups=user_info.get("groups", []),
                        auth_method="active",
                    )

                    # Cache the result
                    self.cache.set(token, user)
                    logger.info(
                        "Token validation successful",
                        username=user.username,
                        uid=user.uid,
                        groups_count=len(user.groups),
                    )
                    return user
                elif response.status_code == 401:
                    logger.warning(
                        "Token validation failed: unauthorized",
                        status=response.status_code,
                    )
                    return None
                else:
                    logger.warning(
                        "Token validation failed: unexpected status",
                        status=response.status_code,
                        response=response.text[:200],
                    )
                    return None

        except httpx.TimeoutException:
            logger.error("Token validation timeout")
            return None
        except httpx.RequestError as e:
            logger.error("Token validation request error", error=str(e))
            return None
        except Exception as e:
            logger.error(
                "Token validation unexpected error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None


class BearerTokenBackend:
    """Authentication backend for OpenShift bearer tokens."""

    def __init__(self, openshift_client: OpenShiftClient):
        """Initialize bearer token backend.

        Args:
            openshift_client: OpenShift client for token validation
        """
        self.openshift_client = openshift_client

    async def authenticate(self, request: Any) -> User | None:
        """Authenticate request using bearer token from Authorization header.

        Args:
            request: HTTP request object

        Returns:
            User object if authentication successful, None otherwise
        """
        # Extract token from Authorization header
        auth_header = getattr(request, "headers", {}).get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.debug("No valid Authorization header found")
            return None

        try:
            token = auth_header.split(" ", 1)[1]
            logger.debug("Token found in Authorization header")
        except IndexError:
            logger.warning("Malformed Authorization header")
            return None

        # Validate token
        return await self.openshift_client.validate_token(token)
