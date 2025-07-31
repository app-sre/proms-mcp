"""Unit tests for OpenShift authentication."""

import os
from unittest.mock import AsyncMock, Mock, mock_open, patch

import httpx
import pytest

from proms_mcp.auth.models import User
from proms_mcp.auth.openshift import BearerTokenBackend, OpenShiftClient


class TestOpenShiftClient:
    """Test OpenShiftClient functionality."""

    def test_initialization(self) -> None:
        """Test OpenShiftClient initialization."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        assert client.api_url == "https://api.cluster.example.com:6443"
        assert (
            client.service_account_token_path
            == "/var/run/secrets/kubernetes.io/serviceaccount/token"
        )
        assert client.cache.ttl_seconds == 300  # default

    def test_initialization_with_custom_params(self) -> None:
        """Test OpenShiftClient initialization with custom parameters."""
        with patch.dict("os.environ", {"AUTH_CACHE_TTL_SECONDS": "600"}):
            client = OpenShiftClient(
                "https://api.cluster.example.com:6443/",  # trailing slash
                "/custom/token/path",
            )
            assert client.api_url == "https://api.cluster.example.com:6443"  # stripped
            assert client.service_account_token_path == "/custom/token/path"
            assert client.cache.ttl_seconds == 600

    @patch("builtins.open", mock_open(read_data="service-account-token"))
    def test_get_service_account_token_success(self) -> None:
        """Test successful service account token reading."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        token = client._get_service_account_token()
        assert token == "service-account-token"

    @patch("builtins.open", side_effect=FileNotFoundError())
    def test_get_service_account_token_not_found(self, mock_open: Mock) -> None:
        """Test service account token file not found."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        token = client._get_service_account_token()
        assert token == ""

    def test_get_service_account_token_from_env(self) -> None:
        """Test service account token from environment variable."""
        with patch.dict("os.environ", {"OPENSHIFT_SERVICE_ACCOUNT_TOKEN": "env-token"}):
            client = OpenShiftClient("https://api.cluster.example.com:6443")
            token = client._get_service_account_token()
            assert token == "env-token"

    def test_get_service_account_token_env_priority(self) -> None:
        """Test that environment variable takes priority over file."""
        with patch.dict("os.environ", {"OPENSHIFT_SERVICE_ACCOUNT_TOKEN": "env-token"}):
            with patch("builtins.open", mock_open(read_data="file-token")):
                client = OpenShiftClient("https://api.cluster.example.com:6443")
                token = client._get_service_account_token()
                assert token == "env-token"

    @pytest.mark.asyncio
    async def test_validate_token_success(self) -> None:
        """Test successful token validation."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"name": "testuser", "uid": "user-123"},
            "groups": ["developers", "admin"],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            user = await client.validate_token("valid-token")

            assert user is not None
            assert user.username == "testuser"
            assert user.uid == "user-123"
            assert user.groups == ["developers", "admin"]
            assert user.auth_method == "active"

    @pytest.mark.asyncio
    async def test_validate_token_unauthorized(self) -> None:
        """Test token validation with unauthorized response."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")

        mock_response = Mock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            user = await client.validate_token("invalid-token")
            assert user is None

    @pytest.mark.asyncio
    async def test_validate_token_timeout(self) -> None:
        """Test token validation timeout."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )

            user = await client.validate_token("test-token")
            assert user is None

    @pytest.mark.asyncio
    async def test_validate_token_request_error(self) -> None:
        """Test token validation with request error."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )

            user = await client.validate_token("test-token")
            assert user is None

    @pytest.mark.asyncio
    async def test_validate_token_cached(self) -> None:
        """Test token validation uses cache."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        user = User(
            username="cached", uid="123", groups=["admin"], auth_method="active"
        )

        # Pre-populate cache
        client.cache.set("cached-token", user)

        # Should return cached user without making HTTP request
        result = await client.validate_token("cached-token")
        assert result is not None
        assert result.username == "cached"

    def test_ssl_verify_config_default(self) -> None:
        """Test default SSL verification configuration."""
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        ssl_config = client._get_ssl_verify_config()
        assert ssl_config is True  # Default should use system CA bundle

    def test_ssl_verify_config_disabled(self) -> None:
        """Test SSL verification disabled via environment variable."""
        with patch.dict("os.environ", {"OPENSHIFT_SSL_VERIFY": "false"}):
            client = OpenShiftClient("https://api.cluster.example.com:6443")
            ssl_config = client._get_ssl_verify_config()
            assert ssl_config is False

    def test_ssl_verify_config_custom_ca(self) -> None:
        """Test SSL verification with custom CA certificate."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as temp_ca:
            temp_ca.write("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----")
            temp_ca_path = temp_ca.name

        try:
            with patch.dict("os.environ", {"OPENSHIFT_CA_CERT_PATH": temp_ca_path}):
                client = OpenShiftClient("https://api.cluster.example.com:6443")
                ssl_config = client._get_ssl_verify_config()
                assert ssl_config == temp_ca_path
        finally:
            os.unlink(temp_ca_path)


class TestBearerTokenBackend:
    """Test BearerTokenBackend functionality."""

    def test_initialization(self) -> None:
        """Test BearerTokenBackend initialization."""
        openshift_client = Mock()
        backend = BearerTokenBackend(openshift_client)
        assert backend.openshift_client == openshift_client

    @pytest.mark.asyncio
    async def test_authenticate_success(self) -> None:
        """Test successful authentication."""
        openshift_client = Mock()
        user = User(username="test", uid="123", groups=["admin"], auth_method="active")
        openshift_client.validate_token = AsyncMock(return_value=user)

        backend = BearerTokenBackend(openshift_client)

        # Mock request with Authorization header
        request = Mock()
        request.headers = {"Authorization": "Bearer valid-token"}

        result = await backend.authenticate(request)
        assert result is not None
        assert result.username == "test"
        openshift_client.validate_token.assert_called_once_with("valid-token")

    @pytest.mark.asyncio
    async def test_authenticate_no_auth_header(self) -> None:
        """Test authentication with no Authorization header."""
        openshift_client = Mock()
        backend = BearerTokenBackend(openshift_client)

        request = Mock()
        request.headers = {}

        result = await backend.authenticate(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_no_bearer_prefix(self) -> None:
        """Test authentication with non-Bearer authorization."""
        openshift_client = Mock()
        backend = BearerTokenBackend(openshift_client)

        request = Mock()
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}

        result = await backend.authenticate(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_malformed_header(self) -> None:
        """Test authentication with malformed Authorization header."""
        openshift_client = Mock()
        backend = BearerTokenBackend(openshift_client)

        request = Mock()
        request.headers = {"Authorization": "Bearer"}  # No token

        result = await backend.authenticate(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_empty_token(self) -> None:
        """Test authentication with empty token."""
        openshift_client = AsyncMock()
        openshift_client.validate_token = AsyncMock(return_value=None)
        backend = BearerTokenBackend(openshift_client)

        request = Mock()
        request.headers = {"Authorization": "Bearer "}  # Empty token

        result = await backend.authenticate(request)
        assert result is None
        # Should call validate_token with empty string
        openshift_client.validate_token.assert_called_once_with("")

    @pytest.mark.asyncio
    async def test_authenticate_invalid_token(self) -> None:
        """Test authentication with invalid token."""
        openshift_client = Mock()
        openshift_client.validate_token = AsyncMock(return_value=None)

        backend = BearerTokenBackend(openshift_client)

        request = Mock()
        request.headers = {"Authorization": "Bearer invalid-token"}

        result = await backend.authenticate(request)
        assert result is None
        openshift_client.validate_token.assert_called_once_with("invalid-token")

    @pytest.mark.asyncio
    async def test_authenticate_request_without_headers_attr(self) -> None:
        """Test authentication with request object without headers attribute."""
        openshift_client = Mock()
        backend = BearerTokenBackend(openshift_client)

        request = Mock(spec=[])  # Mock without headers attribute

        result = await backend.authenticate(request)
        assert result is None
