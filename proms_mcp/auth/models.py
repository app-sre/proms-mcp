"""Authentication models and types."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class User:
    """User information from authentication."""

    username: str
    uid: str
    groups: list[str]
    auth_method: str


class AuthBackend(Protocol):
    """Protocol for authentication backends."""

    async def authenticate(self, request: Any) -> User | None:
        """Authenticate a request and return user info or None if authentication fails."""
        ...
