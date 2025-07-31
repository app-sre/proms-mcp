"""Unit tests for authentication backends."""

from unittest.mock import Mock

import pytest

from proms_mcp.auth.backends import NoAuthBackend


@pytest.mark.asyncio
async def test_no_auth_backend() -> None:
    """Test NoAuthBackend returns a development user."""
    backend = NoAuthBackend()
    mock_request = Mock()

    user = await backend.authenticate(mock_request)

    assert user is not None
    assert user.username == "dev-user"
    assert user.uid == "dev-user-id"
    assert "developers" in user.groups
    assert user.auth_method == "none"


@pytest.mark.asyncio
async def test_no_auth_backend_always_succeeds() -> None:
    """Test NoAuthBackend always returns a user regardless of request."""
    backend = NoAuthBackend()

    # Test with None request
    user1 = await backend.authenticate(None)
    assert user1 is not None
    assert user1.username == "dev-user"

    # Test with empty request
    user2 = await backend.authenticate({})
    assert user2 is not None
    assert user2.username == "dev-user"

    # Both should be equivalent
    assert user1.username == user2.username
    assert user1.auth_method == user2.auth_method
