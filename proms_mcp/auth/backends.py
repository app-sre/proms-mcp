"""Authentication backends implementation."""

from typing import Any

from .models import User


class NoAuthBackend:
    """No authentication - for development only."""

    async def authenticate(self, request: Any) -> User:
        """Return a mock development user."""
        return User(
            username="dev-user",
            uid="dev-user-id",
            groups=["developers"],
            auth_method="none",
        )
