"""FastMCP TokenVerifier using Kubernetes TokenReview API."""

import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken

if TYPE_CHECKING:
    from . import User

logger = structlog.get_logger()


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
            Path to CA certificate file or None for no verification
        """
        if ca_cert_path is not None:
            # Explicit path provided - validate it exists
            if Path(ca_cert_path).exists():
                logger.info("Using explicit CA certificate", path=ca_cert_path)
                return ca_cert_path
            else:
                logger.warning("CA certificate path does not exist", path=ca_cert_path)
                return None

        # Auto-detect in-cluster CA certificate
        in_cluster_ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        if Path(in_cluster_ca).exists():
            logger.info("Using in-cluster CA certificate", path=in_cluster_ca)
            return in_cluster_ca

        # No CA certificate available - will skip verification
        logger.info("No CA certificate found - TLS verification disabled")
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using Kubernetes TokenReview API."""
        try:
            # Validate token and get user identity
            user = await self._validate_token_identity(token)
            if not user:
                logger.debug("Token validation failed")
                return None

            logger.info("Token validated successfully", username=user.username)

            # All authenticated users get read-only access (proms-mcp is read-only)
            return AccessToken(
                token=token,
                client_id=user.username,
                scopes=["read:data"],  # Read-only access for Prometheus queries
                expires_at=int(time.time()) + 3600,  # 1 hour
                resource="proms-mcp-server",
            )

        except Exception as e:
            logger.error("Token verification failed", error=str(e))
            return None

    async def _validate_token_identity(self, token: str) -> "User | None":
        """Validate token using TokenReview API with self-validation.

        The token being validated is also used to authenticate the TokenReview
        request itself. This enables both in-cluster and local development usage.
        """
        from . import User

        payload = {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "spec": {"token": token},
        }

        # Configure HTTP client with optional CA certificate verification
        if self.ca_cert_path:
            verify: str | bool = self.ca_cert_path
        else:
            # Disable TLS verification if no CA certificate available
            verify = False

        async with httpx.AsyncClient(timeout=10.0, verify=verify) as client:
            try:
                response = await client.post(
                    f"{self.api_url}/apis/authentication.k8s.io/v1/tokenreviews",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},  # Self-validation
                )

                if response.status_code != 200:
                    logger.debug(
                        "TokenReview request failed",
                        status_code=response.status_code,
                        response=response.text[:200],
                    )
                    return None

                result = response.json()
                status = result.get("status", {})

                if not status.get("authenticated", False):
                    logger.debug("Token not authenticated by TokenReview")
                    return None

                user_info = status.get("user", {})
                return User(
                    username=user_info.get("username", ""),
                    uid=user_info.get("uid", ""),
                    groups=user_info.get("groups", []),
                    auth_method="tokenreview",
                )

            except httpx.TimeoutException:
                logger.error("TokenReview request timed out")
                return None
            except Exception as e:
                logger.error("TokenReview request failed", error=str(e))
                return None
