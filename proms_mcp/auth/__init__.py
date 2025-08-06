from dataclasses import dataclass
from enum import Enum
from typing import Any


class AuthMode(Enum):
    NONE = "none"
    ACTIVE = "active"


@dataclass
class User:
    """User information from authentication."""

    username: str
    uid: str
    groups: list[str]
    auth_method: str


# Import token verifiers conditionally to avoid circular imports
def __getattr__(name: str) -> Any:
    if name == "TokenReviewVerifier":
        from .tokenreview_auth import TokenReviewVerifier

        return TokenReviewVerifier
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "AuthMode",
    "User",
    "TokenReviewVerifier",
]
