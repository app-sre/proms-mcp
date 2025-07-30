"""Authentication backends for the MCP server."""

from typing import Any

import structlog

from .models import AuthBackend, User

logger = structlog.get_logger()


class NoAuthBackend(AuthBackend):
    """No authentication backend for development."""

    async def authenticate(self, request: Any) -> User | None:
        """Always return a mock user for no-auth mode.

        Args:
            request: HTTP request object

        Returns:
            Mock user object
        """
        return User(
            username="dev-user",
            uid="dev-user-id",
            groups=["developers"],
            auth_method="none"
        )
