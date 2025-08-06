"""Authentication module for proms-mcp server.

Contains authentication models and TokenReview-based token verification.
"""

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx
import structlog
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken

logger = structlog.get_logger()


class AuthMode(Enum):
    """Authentication mode configuration."""

    NONE = "none"
    ACTIVE = "active"


@dataclass
class User:
    """User information from authentication."""

    username: str
    uid: str
    groups: list[str]
    auth_method: str


class TokenReviewVerifier(TokenVerifier):
    """FastMCP TokenVerifier using Kubernetes TokenReview API.

    This implementation uses self-validation: the token being validated
    is also used to authenticate the TokenReview request itself. This
    approach works both in-cluster and for local development.
    """

    def __init__(
        self,
        api_url: str,
        required_scopes: list[str] | None = None,
        ca_cert_path: str | None = None,
    ):
        """Initialize the TokenReview verifier.

        Args:
            api_url: OpenShift/Kubernetes API server URL
            required_scopes: Base scopes required for access
            ca_cert_path: Path to CA certificate file. If None, will try to
                         auto-detect in-cluster CA or use no verification
        """
        super().__init__(
            resource_server_url=None,  # No OAuth2 metadata generation needed
            required_scopes=required_scopes or ["read:data"],
        )
        self.api_url = api_url.rstrip("/")
        self.ca_cert_path = self._resolve_ca_cert_path(ca_cert_path)

    def _resolve_ca_cert_path(self, ca_cert_path: str | None) -> str | None:
        """Resolve CA certificate path with auto-detection for in-cluster usage.

        Args:
            ca_cert_path: Explicit CA cert path or None for auto-detection

        Returns:
            Path to CA certificate file or None (uses system CA store)

        Raises:
            ValueError: If explicit CA cert path is provided but file doesn't exist
        """
        if ca_cert_path is not None:
            # Explicit path provided - must exist or fail
            if Path(ca_cert_path).exists():
                logger.info("Using explicit CA certificate", path=ca_cert_path)
                return ca_cert_path
            else:
                logger.error(
                    "Explicit CA certificate path does not exist", path=ca_cert_path
                )
                raise ValueError(f"CA certificate file not found: {ca_cert_path}")

        # Auto-detect in-cluster CA certificate
        in_cluster_ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        if Path(in_cluster_ca).exists():
            logger.info("Using in-cluster CA certificate", path=in_cluster_ca)
            return in_cluster_ca

        # Use system CA store - never disable TLS verification
        logger.info("Using system CA certificate store for TLS verification")
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using Kubernetes TokenReview API."""
        start_time = time.time()
        token_prefix = token[:8] + "..." if len(token) > 8 else "short-token"
        correlation_id = f"auth-{int(time.time() * 1000)}-{id(token) % 10000}"

        logger.info(
            "Token verification started",
            correlation_id=correlation_id,
            token_prefix=token_prefix,
            token_length=len(token),
            api_url=self.api_url,
            ca_cert_configured=bool(self.ca_cert_path),
            tls_verification="custom_ca" if self.ca_cert_path else "system_ca",
        )

        try:
            # Validate token and get user identity
            user = await self._validate_token_identity(token, correlation_id)
            duration_ms = round((time.time() - start_time) * 1000, 2)

            if not user:
                logger.warning(
                    "Token validation failed",
                    correlation_id=correlation_id,
                    token_prefix=token_prefix,
                    duration_ms=duration_ms,
                    reason="authentication_rejected",
                )
                return None

            logger.info(
                "Token validation successful",
                correlation_id=correlation_id,
                username=user.username,
                uid=user.uid[:8] + "..." if len(user.uid) > 8 else user.uid,
                groups_count=len(user.groups),
                auth_method=user.auth_method,
                duration_ms=duration_ms,
            )

            # All authenticated users get read-only access (proms-mcp is read-only)
            return AccessToken(
                token=token,
                client_id=user.username,
                scopes=["read:data"],  # Read-only access for Prometheus queries
                expires_at=int(time.time()) + 3600,  # 1 hour
                resource="proms-mcp-server",
            )

        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(
                "Token verification failed",
                correlation_id=correlation_id,
                token_prefix=token_prefix,
                duration_ms=duration_ms,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _validate_token_identity(
        self, token: str, correlation_id: str
    ) -> User | None:
        """Validate token using TokenReview API with self-validation.

        The token being validated is also used to authenticate the TokenReview
        request itself. This enables both in-cluster and local development usage.
        """
        payload = {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "spec": {"token": token},
        }

        # Configure HTTP client with proper CA certificate verification
        # Always verify TLS - either with custom CA or system CA store
        if self.ca_cert_path:
            verify: str | bool = self.ca_cert_path  # Use custom CA certificate
        else:
            verify = True  # Use system CA certificate store

        tokenreview_url = f"{self.api_url}/apis/authentication.k8s.io/v1/tokenreviews"

        logger.info(
            "TokenReview API request initiated",
            correlation_id=correlation_id,
            url=tokenreview_url,
            payload_size=len(str(payload)),
            timeout_seconds=10.0,
            tls_verify="custom_ca" if isinstance(verify, str) else "system_ca",
        )

        async with httpx.AsyncClient(timeout=10.0, verify=verify) as client:
            request_start = time.time()
            try:
                response = await client.post(
                    tokenreview_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},  # Self-validation
                )

                request_duration_ms = round((time.time() - request_start) * 1000, 2)

                logger.info(
                    "TokenReview API response received",
                    correlation_id=correlation_id,
                    status_code=response.status_code,
                    response_size=len(response.content),
                    duration_ms=request_duration_ms,
                    content_type=response.headers.get("content-type", "unknown"),
                )

                if response.status_code not in (200, 201):
                    logger.warning(
                        "TokenReview API request failed",
                        correlation_id=correlation_id,
                        status_code=response.status_code,
                        response_preview=response.text[:200],
                        duration_ms=request_duration_ms,
                    )
                    return None

                result = response.json()
                status = result.get("status", {})
                authenticated = status.get("authenticated", False)

                logger.info(
                    "TokenReview API response parsed",
                    correlation_id=correlation_id,
                    authenticated=authenticated,
                    has_user_info=bool(status.get("user")),
                    has_error=bool(status.get("error")),
                )

                if not authenticated:
                    error_info = status.get("error", {})
                    logger.warning(
                        "Token not authenticated by TokenReview",
                        correlation_id=correlation_id,
                        error_code=error_info.get("code"),
                        error_message=error_info.get("message", "No error details"),
                    )
                    return None

                user_info = status.get("user", {})
                username = user_info.get("username", "")
                uid = user_info.get("uid", "")
                groups = user_info.get("groups", [])

                logger.info(
                    "User identity extracted from TokenReview",
                    correlation_id=correlation_id,
                    username=username,
                    uid_prefix=uid[:8] + "..." if len(uid) > 8 else uid,
                    groups_count=len(groups),
                    groups_preview=groups[:3]
                    if groups
                    else [],  # First 3 groups for visibility
                )

                return User(
                    username=username,
                    uid=uid,
                    groups=groups,
                    auth_method="tokenreview",
                )

            except httpx.TimeoutException:
                request_duration_ms = round((time.time() - request_start) * 1000, 2)
                logger.error(
                    "TokenReview API request timed out",
                    correlation_id=correlation_id,
                    timeout_seconds=10.0,
                    duration_ms=request_duration_ms,
                    url=tokenreview_url,
                )
                return None
            except httpx.HTTPStatusError as e:
                request_duration_ms = round((time.time() - request_start) * 1000, 2)
                logger.error(
                    "TokenReview API HTTP error",
                    correlation_id=correlation_id,
                    status_code=e.response.status_code,
                    error_detail=str(e),
                    duration_ms=request_duration_ms,
                    url=tokenreview_url,
                )
                return None
            except Exception as e:
                request_duration_ms = round((time.time() - request_start) * 1000, 2)
                logger.error(
                    "TokenReview API request failed",
                    correlation_id=correlation_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    duration_ms=request_duration_ms,
                    url=tokenreview_url,
                )
                return None


__all__ = [
    "AuthMode",
    "User",
    "TokenReviewVerifier",
]
