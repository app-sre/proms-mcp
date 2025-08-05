"""Authentication middleware for FastMCP integration."""

from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .models import AuthBackend

logger = structlog.get_logger()


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware to handle authentication for all requests."""

    def __init__(self, app: Any, auth_backend: AuthBackend):
        super().__init__(app)
        self.auth_backend = auth_backend

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        """Process request with authentication."""
        # Skip authentication for health checks and metrics endpoints
        unprotected_paths = [
            "/health",
            "/metrics",
        ]
        if request.url.path in unprotected_paths:
            return await call_next(request)

        # Authenticate request
        user = await self.auth_backend.authenticate(request)

        if user is None:
            # Log authentication failure for debugging
            auth_header = getattr(request, "headers", {}).get("Authorization", "")
            logger.warning(
                "Authentication failed",
                path=request.url.path,
                full_url=str(request.url),
                has_auth_header=bool(auth_header),
                auth_header_prefix=auth_header[:20] if auth_header else None,
            )
            return JSONResponse(
                status_code=401, content={"error": "Authentication required"}
            )

        # Add user to request state
        request.state.user = user
        logger.info(
            "Authentication successful", user=user.username, path=request.url.path
        )

        return await call_next(request)
