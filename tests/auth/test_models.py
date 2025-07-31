"""Unit tests for authentication models."""

from proms_mcp.auth.models import User


def test_user_creation() -> None:
    """Test User model creation."""
    user = User(
        username="testuser",
        uid="test-uid-123",
        groups=["admin", "developers"],
        auth_method="test",
    )

    assert user.username == "testuser"
    assert user.uid == "test-uid-123"
    assert user.groups == ["admin", "developers"]
    assert user.auth_method == "test"


def test_user_equality() -> None:
    """Test User model equality."""
    user1 = User(
        username="testuser", uid="test-uid-123", groups=["admin"], auth_method="test"
    )

    user2 = User(
        username="testuser", uid="test-uid-123", groups=["admin"], auth_method="test"
    )

    user3 = User(
        username="different", uid="test-uid-123", groups=["admin"], auth_method="test"
    )

    assert user1 == user2
    assert user1 != user3


def test_user_with_empty_groups() -> None:
    """Test User model with empty groups list."""
    user = User(username="testuser", uid="test-uid-123", groups=[], auth_method="test")

    assert user.groups == []
    assert len(user.groups) == 0
