"""FastMCP authentication integration for OpenShift tokens."""

import time
from typing import TYPE_CHECKING

import structlog
from fastmcp.server.auth import TokenVerifier
from mcp.server.auth.provider import AccessToken

from .models import User

if TYPE_CHECKING:
    from .openshift import OpenShiftClient

logger = structlog.get_logger()


class OpenShiftTokenVerifier(TokenVerifier):
    """FastMCP TokenVerifier for OpenShift bearer tokens.

    Validates both JWT (service account) and opaque (user) tokens
    against the OpenShift API using the existing OpenShiftClient logic.
    """

    def __init__(
        self,
        openshift_client: "OpenShiftClient",
        resource_server_url: str = "http://localhost:8000",
        required_scopes: list[str] | None = None,
    ):
        """Initialize the OpenShift token verifier.

        Args:
            openshift_client: Configured OpenShiftClient instance
            resource_server_url: URL of this MCP server
            required_scopes: Required scopes for access
        """
        super().__init__(
            resource_server_url=resource_server_url,
            required_scopes=required_scopes or ["read:data"],
        )
        self.openshift_client = openshift_client

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify OpenShift token and return AccessToken.

        Args:
            token: Bearer token to validate

        Returns:
            AccessToken if valid, None if invalid
        """
        # Use existing OpenShift client validation
        user = await self.openshift_client.validate_token(token)
        if not user:
            return None

        # Convert User to AccessToken for FastMCP
        return AccessToken(
            token=token,
            client_id=user.username,
            scopes=self._map_user_to_scopes(user),
            expires_at=int(time.time()) + 3600,  # 1 hour default
            resource="proms-mcp-server",
        )

    def _map_user_to_scopes(self, user: User) -> list[str]:
        """Map OpenShift user/groups to scopes.

        Args:
            user: Validated OpenShift user

        Returns:
            List of scopes based on user groups
        """
        scopes = ["read:data"]  # Base scope for all users

        # Add scopes based on OpenShift groups
        if "system:admin" in user.groups:
            scopes.extend(["write:data", "admin:all"])
        elif any(group.startswith("system:") for group in user.groups):
            scopes.append("write:data")

        return scopes
