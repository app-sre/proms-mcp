"""Unit tests for token cache system."""

import time

from proms_mcp.auth.cache import TokenCache
from proms_mcp.auth.models import User


def test_token_cache_initialization() -> None:
    """Test TokenCache initialization."""
    cache = TokenCache(ttl_seconds=600)
    assert cache.ttl_seconds == 600
    assert cache.size() == 0


def test_token_cache_set_and_get() -> None:
    """Test setting and getting cached tokens."""
    cache = TokenCache(ttl_seconds=300)
    user = User(username="test", uid="123", groups=["admin"], auth_method="active")

    # Cache should be empty initially
    assert cache.get("test-token") is None

    # Set and get
    cache.set("test-token", user)
    cached_user = cache.get("test-token")

    assert cached_user is not None
    assert cached_user.username == "test"
    assert cached_user.uid == "123"
    assert cached_user.groups == ["admin"]
    assert cached_user.auth_method == "active"


def test_token_cache_expiration() -> None:
    """Test token cache expiration."""
    cache = TokenCache(ttl_seconds=1)  # 1 second TTL
    user = User(username="test", uid="123", groups=["admin"], auth_method="active")

    # Set token
    cache.set("test-token", user)
    assert cache.get("test-token") is not None

    # Wait for expiration
    time.sleep(1.1)

    # Should be expired now
    assert cache.get("test-token") is None


def test_token_cache_hash_tokens() -> None:
    """Test that tokens are hashed for security."""
    cache = TokenCache()

    # Different tokens should produce different hashes
    hash1 = cache._hash_token("token1")
    hash2 = cache._hash_token("token2")

    assert hash1 != hash2
    assert len(hash1) == 16  # SHA256 truncated to 16 chars
    assert len(hash2) == 16


def test_token_cache_cleanup() -> None:
    """Test cache cleanup of expired entries."""
    cache = TokenCache(ttl_seconds=1)
    user = User(username="test", uid="123", groups=["admin"], auth_method="active")

    # Add multiple tokens
    cache.set("token1", user)
    cache.set("token2", user)
    assert cache.size() == 2

    # Wait for expiration
    time.sleep(1.1)

    # Access one token to trigger cleanup
    cache.get("token1")

    # Cache should be cleaned up
    assert cache.size() == 0


def test_token_cache_clear() -> None:
    """Test clearing the cache."""
    cache = TokenCache()
    user = User(username="test", uid="123", groups=["admin"], auth_method="active")

    cache.set("token1", user)
    cache.set("token2", user)
    assert cache.size() == 2

    cache.clear()
    assert cache.size() == 0
    assert cache.get("token1") is None
    assert cache.get("token2") is None


def test_token_cache_different_tokens() -> None:
    """Test that different tokens are cached separately."""
    cache = TokenCache()
    user1 = User(username="user1", uid="123", groups=["admin"], auth_method="active")
    user2 = User(username="user2", uid="456", groups=["user"], auth_method="active")

    cache.set("token1", user1)
    cache.set("token2", user2)

    cached_user1 = cache.get("token1")
    cached_user2 = cache.get("token2")

    assert cached_user1 is not None
    assert cached_user2 is not None
    assert cached_user1.username == "user1"
    assert cached_user2.username == "user2"
