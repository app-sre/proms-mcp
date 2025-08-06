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


# Import OpenShiftTokenVerifier conditionally to avoid circular imports
def __getattr__(name: str) -> Any:
    if name == "OpenShiftTokenVerifier":
        from .fastmcp_auth import OpenShiftTokenVerifier

        return OpenShiftTokenVerifier
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "AuthMode",
    "User",
    "OpenShiftTokenVerifier",
]
