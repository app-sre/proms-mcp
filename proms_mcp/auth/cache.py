"""Token validation caching system."""

import hashlib
import time

import structlog

from . import User

logger = structlog.get_logger()


class TokenCache:
    """In-memory cache for token validation results."""

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache with TTL in seconds (default: 5 minutes)."""
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[User, float]] = {}

    def _hash_token(self, token: str) -> str:
        """Hash token for cache key to prevent token leakage in logs."""
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def get(self, token: str) -> User | None:
        """Get cached user for token if not expired."""
        cache_key = self._hash_token(token)

        if cache_key not in self._cache:
            return None

        user, timestamp = self._cache[cache_key]

        # Check if expired
        if time.time() - timestamp > self.ttl_seconds:
            self._cleanup_expired(cache_key)
            return None

        logger.debug("Token validation cache hit", cache_key=cache_key)
        return user

    def set(self, token: str, user: User) -> None:
        """Cache user for token."""
        cache_key = self._hash_token(token)
        self._cache[cache_key] = (user, time.time())
        logger.debug(
            "Token validation cached", cache_key=cache_key, username=user.username
        )

    def _cleanup_expired(self, expired_key: str | None = None) -> None:
        """Remove expired entries from cache."""
        current_time = time.time()
        expired_keys = []

        for key, (_, timestamp) in self._cache.items():
            if current_time - timestamp > self.ttl_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
        logger.debug("Token cache cleared")

    def size(self) -> int:
        """Return current cache size."""
        return len(self._cache)
