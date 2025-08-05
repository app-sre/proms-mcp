"""Tests for authentication middleware."""

from unittest.mock import AsyncMock, Mock

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.testclient import TestClient

from proms_mcp.auth.backends import NoAuthBackend
from proms_mcp.auth.middleware import AuthenticationMiddleware
from proms_mcp.auth.models import User


class TestAuthenticationMiddleware:
    """Test the authentication middleware."""

    def test_unprotected_endpoints_no_auth_required(self) -> None:
        """Test that unprotected endpoints don't require authentication."""
        # Create a simple Starlette app for testing
        app = Starlette()

        @app.route("/health")
        async def health(request: Request) -> PlainTextResponse:
            return PlainTextResponse("OK")

        @app.route("/metrics")
        async def metrics(request: Request) -> PlainTextResponse:
            return PlainTextResponse("# metrics")

        @app.route("/.well-known/oauth-protected-resource")
        async def oauth_protected_resource(request: Request) -> JSONResponse:
            return JSONResponse({"resource_server": "test"})

        @app.route("/.well-known/oauth-authorization-server")
        async def oauth_authorization_server(request: Request) -> JSONResponse:
            return JSONResponse({"issuer": "test"})

        @app.route("/protected")
        async def protected(request: Request) -> PlainTextResponse:
            return PlainTextResponse("Protected content")

        # Create a mock auth backend that always fails
        mock_auth_backend = Mock()
        mock_auth_backend.authenticate = AsyncMock(return_value=None)

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=mock_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test unprotected endpoints - should work without authentication
        response = client.get("/health")
        assert response.status_code == 200
        assert response.text == "OK"

        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.text == "# metrics"

        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        assert response.json() == {"resource_server": "test"}

        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        assert response.json() == {"issuer": "test"}

        # Test protected endpoint - should fail without authentication
        response = client.get("/protected")
        assert response.status_code == 401
        assert response.json() == {"error": "Authentication required"}

        # Verify that authenticate was called for protected endpoint but not unprotected ones
        # The mock should have been called only once for the protected endpoint
        assert mock_auth_backend.authenticate.call_count == 1

    def test_protected_endpoint_with_valid_auth(self) -> None:
        """Test that protected endpoints work with valid authentication."""
        # Create a simple Starlette app
        app = Starlette()

        @app.route("/protected")
        async def protected(request: Request) -> PlainTextResponse:
            user = getattr(request.state, "user", None)
            if user:
                return PlainTextResponse(f"Hello {user.username}")
            return PlainTextResponse("No user")

        # Create a mock auth backend that returns a valid user
        mock_user = User(
            username="testuser",
            uid="test-uid",
            groups=["test-group"],
            auth_method="bearer",
        )
        mock_auth_backend = Mock()
        mock_auth_backend.authenticate = AsyncMock(return_value=mock_user)

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=mock_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test protected endpoint with valid auth
        response = client.get(
            "/protected", headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200
        assert response.text == "Hello testuser"

        # Verify authenticate was called
        mock_auth_backend.authenticate.assert_called_once()

    def test_protected_endpoint_with_invalid_auth(self) -> None:
        """Test that protected endpoints fail with invalid authentication."""
        # Create a simple Starlette app
        app = Starlette()

        @app.route("/protected")
        async def protected(request: Request) -> PlainTextResponse:
            return PlainTextResponse("Protected content")

        # Create a mock auth backend that returns None (auth failure)
        mock_auth_backend = Mock()
        mock_auth_backend.authenticate = AsyncMock(return_value=None)

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=mock_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test protected endpoint with invalid auth
        response = client.get(
            "/protected", headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401
        assert response.json() == {"error": "Authentication required"}

        # Verify authenticate was called
        mock_auth_backend.authenticate.assert_called_once()

    def test_middleware_with_no_auth_backend(self) -> None:
        """Test middleware behavior with NoAuthBackend."""
        # Create a simple Starlette app
        app = Starlette()

        @app.route("/protected")
        async def protected(request: Request) -> PlainTextResponse:
            user = getattr(request.state, "user", None)
            if user:
                return PlainTextResponse(f"Hello {user.username}")
            return PlainTextResponse("No user")

        # Use NoAuthBackend
        no_auth_backend = NoAuthBackend()

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=no_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test that all endpoints work with NoAuthBackend
        response = client.get("/protected")
        assert response.status_code == 200
        assert response.text == "Hello dev-user"

    def test_middleware_logs_authentication_failure(self) -> None:
        """Test that authentication failures are properly logged."""
        # Create a simple Starlette app
        app = Starlette()

        @app.route("/protected")
        async def protected(request: Request) -> PlainTextResponse:
            return PlainTextResponse("Protected content")

        # Create a mock auth backend that fails
        mock_auth_backend = Mock()
        mock_auth_backend.authenticate = AsyncMock(return_value=None)

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=mock_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test with no auth header
        response = client.get("/protected")
        assert response.status_code == 401

        # Test with auth header
        response = client.get(
            "/protected", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 401

        # Verify authenticate was called twice
        assert mock_auth_backend.authenticate.call_count == 2

    def test_middleware_adds_user_to_request_state(self) -> None:
        """Test that successful authentication adds user to request state."""
        # Create a simple Starlette app
        app = Starlette()

        @app.route("/user-info")
        async def user_info(request: Request) -> JSONResponse:
            user = getattr(request.state, "user", None)
            if user:
                return JSONResponse(
                    {
                        "username": user.username,
                        "uid": user.uid,
                        "groups": user.groups,
                        "auth_method": user.auth_method,
                    }
                )
            return JSONResponse({"error": "No user"})

        # Create a mock user and auth backend
        mock_user = User(
            username="testuser",
            uid="test-uid-123",
            groups=["group1", "group2"],
            auth_method="bearer",
        )
        mock_auth_backend = Mock()
        mock_auth_backend.authenticate = AsyncMock(return_value=mock_user)

        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, auth_backend=mock_auth_backend)

        # Create test client
        client = TestClient(app)

        # Test that user info is accessible in the endpoint
        response = client.get(
            "/user-info", headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200

        user_data = response.json()
        assert user_data["username"] == "testuser"
        assert user_data["uid"] == "test-uid-123"
        assert user_data["groups"] == ["group1", "group2"]
        assert user_data["auth_method"] == "bearer"
