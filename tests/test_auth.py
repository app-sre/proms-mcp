"""Tests for authentication functionality."""

import json
import os
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.server.auth.auth import AccessToken

from proms_mcp.auth import AuthMode, OpenShiftUserVerifier, User, clear_auth_cache
from proms_mcp.config import get_auth_mode


# User model tests
def test_user_creation() -> None:
    """Test User model creation."""
    user = User(
        username="testuser",
        uid="test-uid-123",
        auth_method="test",
    )

    assert user.username == "testuser"
    assert user.uid == "test-uid-123"
    assert user.auth_method == "test"


def test_user_equality() -> None:
    """Test User model equality."""
    user1 = User(username="testuser", uid="test-uid-123", auth_method="test")

    user2 = User(username="testuser", uid="test-uid-123", auth_method="test")

    user3 = User(username="different", uid="test-uid-123", auth_method="test")

    assert user1 == user2
    assert user1 != user3


# Auth config tests
def test_get_auth_mode_default() -> None:
    """Test get_auth_mode returns ACTIVE by default."""
    with patch.dict(os.environ, {}, clear=True):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


def test_get_auth_mode_none() -> None:
    """Test get_auth_mode with AUTH_MODE=none."""
    with patch.dict(os.environ, {"AUTH_MODE": "none"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE


def test_get_auth_mode_active() -> None:
    """Test get_auth_mode with AUTH_MODE=active."""
    with patch.dict(os.environ, {"AUTH_MODE": "active"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


def test_get_auth_mode_case_insensitive() -> None:
    """Test get_auth_mode is case insensitive."""
    with patch.dict(os.environ, {"AUTH_MODE": "NONE"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE

    with patch.dict(os.environ, {"AUTH_MODE": "Active"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


def test_get_auth_mode_invalid_defaults_to_active() -> None:
    """Test get_auth_mode defaults to ACTIVE for invalid values."""
    with patch.dict(os.environ, {"AUTH_MODE": "invalid"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


# TokenReview tests (consolidated from the original test_tokenreview_auth.py)
class TestOpenShiftUserVerifier:
    """Test cases for OpenShiftUserVerifier class."""

    @pytest.fixture(autouse=True)
    def clear_cache(self) -> None:
        """Clear auth cache before each test."""
        clear_auth_cache()

    @pytest.fixture
    def verifier(self) -> OpenShiftUserVerifier:
        """Create a OpenShiftUserVerifier instance for testing."""
        return OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443",
            required_scopes=["read:data"],
            ca_cert_path=None,
        )

    @pytest.fixture
    def mock_successful_userinfo_response(self) -> dict:
        """Mock successful OpenShift user info API response."""
        return {
            "kind": "User",
            "apiVersion": "user.openshift.io/v1",
            "metadata": {
                "name": "testuser",
                "uid": "12345-67890-abcdef",
                "creationTimestamp": "2023-01-01T00:00:00Z",
            },
            "identities": [],
        }

    @pytest.fixture
    def mock_failed_userinfo_response(self) -> dict:
        """Mock failed OpenShift user info API response (401 error)."""
        return {
            "kind": "Status",
            "apiVersion": "v1",
            "status": "Failure",
            "message": "Unauthorized",
            "code": 401,
        }

    def test_init(self) -> None:
        """Test OpenShiftUserVerifier initialization."""
        verifier = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443/",
            required_scopes=["read:data"],
        )

        assert verifier.api_url == "https://api.cluster.example.com:6443"
        assert verifier.required_scopes == ["read:data"]

    def test_init_defaults(self) -> None:
        """Test OpenShiftUserVerifier initialization with defaults."""
        verifier = OpenShiftUserVerifier(api_url="https://api.cluster.example.com:6443")

        assert verifier.required_scopes == ["read:data"]

    @pytest.mark.asyncio
    async def test_verify_token_success(
        self, verifier: OpenShiftUserVerifier, mock_successful_userinfo_response: dict
    ) -> None:
        """Test successful token verification."""
        token = "valid-bearer-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": "success"}'  # Mock content for logging
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": "success"}'
            mock_response.json.return_value = mock_successful_userinfo_response
            mock_client.get.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is not None
            assert isinstance(access_token, AccessToken)
            assert access_token.token == token
            assert access_token.client_id == "testuser"
            assert access_token.scopes == [
                "read:data"
            ]  # Only read access for proms-mcp
            assert access_token.resource == "proms-mcp-server"
            assert access_token.expires_at is not None
            assert access_token.expires_at > int(time.time())

            # Verify the API call
            mock_client.get.assert_called_once_with(
                "https://api.cluster.example.com:6443/apis/user.openshift.io/v1/users/~",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "proms-mcp/1.0.0",
                },
            )

    @pytest.mark.asyncio
    async def test_verify_token_authentication_failed(
        self, verifier: OpenShiftUserVerifier, mock_failed_userinfo_response: dict
    ) -> None:
        """Test token verification when authentication fails."""
        token = "invalid-bearer-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.content = b'{"status": "Failure"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": "Failure"}'
            mock_response.json.return_value = mock_failed_userinfo_response
            mock_client.get.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_api_error(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test token verification when API returns error."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.text = "Unauthorized"
            mock_response.content = b"Unauthorized"
            mock_response.headers = {"content-type": "text/plain"}
            mock_client.get.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_timeout(self, verifier: OpenShiftUserVerifier) -> None:
        """Test token verification with timeout."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.get.side_effect = httpx.TimeoutException("Request timed out")

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_http_error(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test token verification with HTTP error."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.get.side_effect = httpx.HTTPError("Network error")

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_json_decode_error(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test token verification with invalid JSON response."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b"invalid json"
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = "invalid json"
            mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
            mock_client.get.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_validate_token_identity_success(
        self, verifier: OpenShiftUserVerifier, mock_successful_userinfo_response: dict
    ) -> None:
        """Test successful token identity validation."""
        token = "valid-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "User"}'  # Mock content for logging
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User"}'
            mock_response.json.return_value = mock_successful_userinfo_response
            mock_client.get.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert isinstance(user, User)
            assert user.username == "testuser"
            assert user.uid == "12345-67890-abcdef"

            assert user.auth_method == "openshift-userinfo"

    @pytest.mark.asyncio
    async def test_validate_token_identity_missing_user_info(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test token identity validation with missing user info."""
        token = "valid-token"

        response_without_metadata = {
            "kind": "User",
            "apiVersion": "user.openshift.io/v1",
            # Missing metadata field
            "identities": [],
        }

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "User"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User"}'
            mock_response.json.return_value = response_without_metadata
            mock_client.get.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert user.username == ""
            assert user.uid == ""

            assert user.auth_method == "openshift-userinfo"

    @pytest.mark.asyncio
    async def test_validate_token_identity_partial_user_info(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test token identity validation with partial user info."""
        token = "valid-token"

        response_partial_user = {
            "kind": "User",
            "apiVersion": "user.openshift.io/v1",
            "metadata": {
                "name": "testuser"
                # Missing uid
            },
            "identities": [],
        }

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = (
                b'{"kind": "User", "metadata": {"name": "testuser"}}'
            )
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User", "metadata": {"name": "testuser"}}'
            mock_response.json.return_value = response_partial_user
            mock_client.get.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert user.username == "testuser"
            assert user.uid == ""

            assert user.auth_method == "openshift-userinfo"

    @pytest.mark.asyncio
    async def test_client_timeout_configuration(
        self, verifier: OpenShiftUserVerifier
    ) -> None:
        """Test that HTTP client is configured with correct timeout."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "Status", "status": "Failure"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "Status", "status": "Failure"}'
            mock_response.json.return_value = {"kind": "Status", "status": "Failure"}
            mock_client.get.return_value = mock_response

            await verifier._validate_token_identity(token)

            # Verify client was created with correct timeout and verify settings
            mock_client_class.assert_called_once_with(timeout=10.0, verify=True)

    def test_api_url_normalization(self) -> None:
        """Test that API URL is normalized correctly."""
        verifier_with_trailing_slash = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443/"
        )
        verifier_without_trailing_slash = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443"
        )

        assert (
            verifier_with_trailing_slash.api_url
            == "https://api.cluster.example.com:6443"
        )
        assert (
            verifier_without_trailing_slash.api_url
            == "https://api.cluster.example.com:6443"
        )

    def test_ca_cert_path_explicit(self) -> None:
        """Test explicit CA certificate path."""
        with patch("proms_mcp.auth.Path.exists", return_value=True):
            verifier = OpenShiftUserVerifier(
                api_url="https://api.cluster.example.com:6443",
                ca_cert_path="/custom/ca.crt",
            )
            assert verifier.ca_cert_path == "/custom/ca.crt"

    def test_ca_cert_path_explicit_not_exists(self) -> None:
        """Test explicit CA certificate path that doesn't exist - should raise ValueError."""
        with patch("proms_mcp.auth.Path.exists", return_value=False):
            with pytest.raises(
                ValueError, match="CA certificate file not found: /nonexistent/ca.crt"
            ):
                OpenShiftUserVerifier(
                    api_url="https://api.cluster.example.com:6443",
                    ca_cert_path="/nonexistent/ca.crt",
                )

    @pytest.mark.asyncio
    async def test_tls_verification_always_enabled(self) -> None:
        """Test that TLS verification is always enabled - never disabled."""
        verifier = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443",
            ca_cert_path=None,  # No explicit CA cert
        )
        token = "test-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "User"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User"}'
            mock_response.json.return_value = {"kind": "User", "metadata": {}}
            mock_client.get.return_value = mock_response

            await verifier._validate_token_identity(token)

            # Verify TLS verification is enabled (verify=True for system CA store)
            mock_client_class.assert_called_once_with(timeout=10.0, verify=True)

    def test_ca_cert_path_auto_detect_in_cluster(self) -> None:
        """Test auto-detection of in-cluster CA certificate."""

        def mock_exists(self: object) -> bool:
            return str(self) == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        with patch("proms_mcp.auth.Path.exists", mock_exists):
            verifier = OpenShiftUserVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert (
                verifier.ca_cert_path
                == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            )

    def test_ca_cert_path_no_cert_available(self) -> None:
        """Test when no CA certificate is available."""
        with patch("proms_mcp.auth.Path.exists", return_value=False):
            verifier = OpenShiftUserVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert verifier.ca_cert_path is None

    @pytest.mark.asyncio
    async def test_service_account_authentication(self) -> None:
        """Test that service accounts can authenticate successfully."""
        verifier = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443", ca_cert_path=None
        )
        token = "test-token"

        service_account_response = {
            "kind": "User",
            "apiVersion": "user.openshift.io/v1",
            "metadata": {
                "name": "system:serviceaccount:test-namespace:test-sa",
                "uid": "12345-67890-abcdef",
                "creationTimestamp": "2023-01-01T00:00:00Z",
            },
            "identities": [],
        }

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "User"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User"}'
            mock_response.json.return_value = service_account_response
            mock_client.get.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert user.username == "system:serviceaccount:test-namespace:test-sa"
            assert user.uid == "12345-67890-abcdef"
            assert user.auth_method == "openshift-userinfo"

    @pytest.mark.asyncio
    async def test_network_error_logging(self) -> None:
        """Test that network errors are logged as ERROR while token errors are WARNING."""
        verifier = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443", ca_cert_path=None
        )
        token = "test-token"

        # Test network error (should log as ERROR)
        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("Connection failed")

            with patch("proms_mcp.auth.logger") as mock_logger:
                user = await verifier._validate_token_identity(token)

                assert user is None
                # Verify ERROR log for network issues
                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args[0]  # Get positional arguments
                assert "cannot reach OpenShift API" in call_args[0]

        # Test token error (should not log ERROR in _validate_token_identity)
        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 401  # Invalid token
            mock_client.get.return_value = mock_response

            with patch("proms_mcp.auth.logger") as mock_logger:
                user = await verifier._validate_token_identity(token)

                assert user is None
                # Verify NO ERROR log for token issues (handled at higher level)
                mock_logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_authentication_caching(self) -> None:
        """Test that successful authentication results are cached."""
        verifier = OpenShiftUserVerifier(
            api_url="https://api.cluster.example.com:6443", ca_cert_path=None
        )
        token = "cache-test-token"

        user_response = {
            "kind": "User",
            "apiVersion": "user.openshift.io/v1",
            "metadata": {
                "name": "cached-user",
                "uid": "cached-uid-123",
                "creationTimestamp": "2023-01-01T00:00:00Z",
            },
            "identities": [],
        }

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"kind": "User"}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"kind": "User"}'
            mock_response.json.return_value = user_response
            mock_client.get.return_value = mock_response

            # First call - should hit the API
            user1 = await verifier._validate_token_identity(token)
            assert user1 is not None
            assert user1.username == "cached-user"
            assert user1.uid == "cached-uid-123"

            # Second call with same token - should use cache
            user2 = await verifier._validate_token_identity(token)
            assert user2 is not None
            assert user2.username == "cached-user"
            assert user2.uid == "cached-uid-123"

            # Verify API was only called once (first call), second was cached
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_auth_cache_ttl_environment_variable(self) -> None:
        """Test that AUTH_CACHE_TTL_SECONDS environment variable is respected."""
        import os
        from unittest.mock import patch

        # Test with custom TTL
        with patch.dict(os.environ, {"AUTH_CACHE_TTL_SECONDS": "600"}):
            # Re-import to get new cache with updated TTL
            import importlib

            import proms_mcp.auth

            importlib.reload(proms_mcp.auth)

            # Verify the cache was created with the custom TTL
            assert proms_mcp.auth._AUTH_CACHE_TTL_SECONDS == 600
            assert proms_mcp.auth._auth_cache.ttl == 600

        # Clean up and restore original module state
        importlib.reload(proms_mcp.auth)

    @pytest.mark.asyncio
    async def test_auth_cache_disable_with_ttl_zero(self) -> None:
        """Test that AUTH_CACHE_TTL_SECONDS=0 disables caching."""
        import os
        from unittest.mock import patch

        # Test cache disable with TTL=0
        with patch.dict(os.environ, {"AUTH_CACHE_TTL_SECONDS": "0"}):
            # Re-import to get new cache with TTL=0
            import importlib

            import proms_mcp.auth

            importlib.reload(proms_mcp.auth)

            # Verify the cache was created with TTL=0
            assert proms_mcp.auth._AUTH_CACHE_TTL_SECONDS == 0
            assert proms_mcp.auth._auth_cache.ttl == 0

            # Test that caching is actually disabled
            verifier = proms_mcp.auth.OpenShiftUserVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            token = "disable-cache-test-token"

            user_response = {
                "kind": "User",
                "apiVersion": "user.openshift.io/v1",
                "metadata": {
                    "name": "no-cache-user",
                    "uid": "no-cache-uid-123",
                    "creationTimestamp": "2023-01-01T00:00:00Z",
                },
                "identities": [],
            }

            with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client

                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.content = b'{"kind": "User"}'
                mock_response.headers = {"content-type": "application/json"}
                mock_response.text = '{"kind": "User"}'
                mock_response.json.return_value = user_response
                mock_client.get.return_value = mock_response

                # First call
                user1 = await verifier._validate_token_identity(token)
                assert user1 is not None
                assert user1.username == "no-cache-user"

                # Second call with same token - should call API again (not cached)
                user2 = await verifier._validate_token_identity(token)
                assert user2 is not None
                assert user2.username == "no-cache-user"

                # Verify API was called twice (no caching occurred)
                assert mock_client.get.call_count == 2

        # Clean up and restore original module state
        importlib.reload(proms_mcp.auth)
