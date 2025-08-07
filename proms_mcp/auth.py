"""Authentication module for proms-mcp server.

Contains authentication models and OpenShift user info based token verification.
"""

import hashlib
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx
import structlog
from asyncache import cached  # type: ignore[import-untyped]
from cachetools import TTLCache
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken

logger = structlog.get_logger()

# Auth cache TTL from environment (default: 5 minutes)
_AUTH_CACHE_TTL_SECONDS = int(os.getenv("AUTH_CACHE_TTL_SECONDS", "300"))

# Authentication cache: configurable TTL, max 1000 entries, thread-safe
_auth_cache: TTLCache[str, "User | None"] = TTLCache(
    maxsize=1000, ttl=_AUTH_CACHE_TTL_SECONDS
)


def _cache_key(token: str) -> str:
    """Secure cache key from token hash."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def clear_auth_cache() -> None:
    """Clear the authentication cache. Useful for testing."""
    _auth_cache.clear()


class AuthMode(Enum):
    """Authentication mode configuration."""

    NONE = "none"
    ACTIVE = "active"


@dataclass
class User:
    """User information from authentication."""

    username: str
    uid: str
    auth_method: str


class OpenShiftUserVerifier(TokenVerifier):
    """FastMCP TokenVerifier using OpenShift user info endpoint.

    This implementation uses the OpenShift user info API (/apis/user.openshift.io/v1/users/~)
    to validate tokens. This endpoint is accessible to all authenticated users and doesn't
    require special permissions like system:auth-delegator.
    """

    def __init__(
        self,
        api_url: str,
        required_scopes: list[str] | None = None,
        ca_cert_path: str | None = None,
    ):
        """Initialize the OpenShift user info verifier.

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
        """Verify token using OpenShift user info API."""
        # Validate token and get user identity
        user = await self._validate_token_identity(token)

        if not user:
            logger.warning("Authentication failed - invalid token")
            return None

        logger.info(
            "Authentication successful",
            username=user.username,
        )

        # All authenticated users get read-only access (proms-mcp is read-only)
        return AccessToken(
            token=token,
            client_id=user.username,
            scopes=["read:data"],  # Read-only access for Prometheus queries
            expires_at=int(time.time()) + 3600,  # 1 hour
            resource="proms-mcp-server",
        )

    @cached(_auth_cache, key=lambda self, token: _cache_key(token))  # type: ignore[misc]
    async def _validate_token_identity(self, token: str) -> User | None:
        """Validate token using OpenShift user info API.

        Uses the /apis/user.openshift.io/v1/users/~ endpoint which is accessible
        to all authenticated users without requiring special permissions.
        """
        # Configure HTTP client with proper CA certificate verification
        if self.ca_cert_path:
            # Use custom CA certificate with ssl.create_default_context()
            ssl_context = ssl.create_default_context(cafile=self.ca_cert_path)
            verify: ssl.SSLContext | bool = ssl_context
        else:
            # Use system CA certificate store
            verify = True

        userinfo_url = f"{self.api_url}/apis/user.openshift.io/v1/users/~"

        async with httpx.AsyncClient(timeout=10.0, verify=verify) as client:
            try:
                response = await client.get(
                    userinfo_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "User-Agent": "proms-mcp/1.0.0",
                    },
                )

                if response.status_code not in (200, 201):
                    return None

                result = response.json()

                # Extract user information from OpenShift user object
                username = result.get("metadata", {}).get("name", "")
                uid = result.get("metadata", {}).get("uid", "")

                return User(
                    username=username,
                    uid=uid,
                    auth_method="openshift-userinfo",
                )

            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
            ) as e:
                # These are system errors - we can't reach OpenShift API
                logger.error(
                    "Authentication failed - cannot reach OpenShift API",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return None
            except Exception:
                # Other errors (like JSON parsing) are also user/token issues
                return None


__all__ = [
    "AuthMode",
    "User",
    "OpenShiftUserVerifier",
]
