from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .fastmcp_auth import OpenShiftTokenVerifier


class AuthMode(Enum):
    NONE = "none"
    ACTIVE = "active"


@dataclass
class User:
    username: str
    uid: str
    groups: list[str]
    auth_method: str


class AuthBackend(Protocol):
    async def authenticate(self, request: Any) -> User | None: ...


__all__ = [
    "AuthMode",
    "User",
    "AuthBackend",
    "OpenShiftTokenVerifier",
]
