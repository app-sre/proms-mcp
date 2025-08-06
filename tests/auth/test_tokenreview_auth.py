"""Tests for TokenReview-based authentication."""

import json
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.server.auth.auth import AccessToken

from proms_mcp.auth import User
from proms_mcp.auth.tokenreview_auth import TokenReviewVerifier


class TestTokenReviewVerifier:
    """Test cases for TokenReviewVerifier class."""

    @pytest.fixture
    def verifier(self) -> TokenReviewVerifier:
        """Create a TokenReviewVerifier instance for testing."""
        return TokenReviewVerifier(
            api_url="https://api.cluster.example.com:6443",
            required_scopes=["read:data"],
            ca_cert_path=None,
        )

    @pytest.fixture
    def mock_successful_tokenreview_response(self) -> dict:
        """Mock successful TokenReview API response."""
        return {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "status": {
                "authenticated": True,
                "user": {
                    "username": "testuser",
                    "uid": "12345-67890-abcdef",
                    "groups": ["system:authenticated", "myteam"],
                },
            },
        }

    @pytest.fixture
    def mock_failed_tokenreview_response(self) -> dict:
        """Mock failed TokenReview API response."""
        return {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "status": {"authenticated": False},
        }

    def test_init(self) -> None:
        """Test TokenReviewVerifier initialization."""
        verifier = TokenReviewVerifier(
            api_url="https://api.cluster.example.com:6443/",
            required_scopes=["read:data"],
        )

        assert verifier.api_url == "https://api.cluster.example.com:6443"
        assert verifier.required_scopes == ["read:data"]

    def test_init_defaults(self) -> None:
        """Test TokenReviewVerifier initialization with defaults."""
        verifier = TokenReviewVerifier(api_url="https://api.cluster.example.com:6443")

        assert verifier.required_scopes == ["read:data"]

    @pytest.mark.asyncio
    async def test_verify_token_success(
        self, verifier: TokenReviewVerifier, mock_successful_tokenreview_response: dict
    ) -> None:
        """Test successful token verification."""
        token = "valid-bearer-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_tokenreview_response
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is not None
            assert isinstance(access_token, AccessToken)
            assert access_token.token == token
            assert access_token.client_id == "testuser"
            assert access_token.scopes == ["read:data"]  # Only read access for proms-mcp
            assert access_token.resource == "proms-mcp-server"
            assert access_token.expires_at is not None
            assert access_token.expires_at > int(time.time())

            # Verify the API call
            mock_client.post.assert_called_once_with(
                "https://api.cluster.example.com:6443/apis/authentication.k8s.io/v1/tokenreviews",
                json={
                    "kind": "TokenReview",
                    "apiVersion": "authentication.k8s.io/v1",
                    "spec": {"token": token},
                },
                headers={"Authorization": f"Bearer {token}"},
            )

    @pytest.mark.asyncio
    async def test_verify_token_authentication_failed(
        self, verifier: TokenReviewVerifier, mock_failed_tokenreview_response: dict
    ) -> None:
        """Test token verification when authentication fails."""
        token = "invalid-bearer-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_failed_tokenreview_response
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_api_error(self, verifier: TokenReviewVerifier) -> None:
        """Test token verification when API returns error."""
        token = "some-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.text = "Unauthorized"
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_timeout(self, verifier: TokenReviewVerifier) -> None:
        """Test token verification with timeout."""
        token = "some-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.post.side_effect = httpx.TimeoutException("Request timed out")

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_http_error(self, verifier: TokenReviewVerifier) -> None:
        """Test token verification with HTTP error."""
        token = "some-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.post.side_effect = httpx.HTTPError("Network error")

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_json_decode_error(
        self, verifier: TokenReviewVerifier
    ) -> None:
        """Test token verification with invalid JSON response."""
        token = "some-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_validate_token_identity_success(
        self, verifier: TokenReviewVerifier, mock_successful_tokenreview_response: dict
    ) -> None:
        """Test successful token identity validation."""
        token = "valid-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_successful_tokenreview_response
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert isinstance(user, User)
            assert user.username == "testuser"
            assert user.uid == "12345-67890-abcdef"
            assert user.groups == ["system:authenticated", "myteam"]
            assert user.auth_method == "tokenreview"

    @pytest.mark.asyncio
    async def test_validate_token_identity_missing_user_info(
        self, verifier: TokenReviewVerifier
    ) -> None:
        """Test token identity validation with missing user info."""
        token = "valid-token"

        response_without_user = {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "status": {
                "authenticated": True
                # Missing user field
            },
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_without_user
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert user.username == ""
            assert user.uid == ""
            assert user.groups == []
            assert user.auth_method == "tokenreview"

    @pytest.mark.asyncio
    async def test_validate_token_identity_partial_user_info(
        self, verifier: TokenReviewVerifier
    ) -> None:
        """Test token identity validation with partial user info."""
        token = "valid-token"

        response_partial_user = {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "status": {
                "authenticated": True,
                "user": {
                    "username": "testuser"
                    # Missing uid and groups
                },
            },
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_partial_user
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token)

            assert user is not None
            assert user.username == "testuser"
            assert user.uid == ""
            assert user.groups == []
            assert user.auth_method == "tokenreview"

    @pytest.mark.asyncio
    async def test_client_timeout_configuration(
        self, verifier: TokenReviewVerifier
    ) -> None:
        """Test that HTTP client is configured with correct timeout."""
        token = "some-token"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": {"authenticated": False}}
            mock_client.post.return_value = mock_response

            await verifier._validate_token_identity(token)

            # Verify client was created with correct timeout and verify settings
            mock_client_class.assert_called_once_with(timeout=10.0, verify=False)

    def test_api_url_normalization(self) -> None:
        """Test that API URL is normalized correctly."""
        verifier_with_trailing_slash = TokenReviewVerifier(
            api_url="https://api.cluster.example.com:6443/"
        )
        verifier_without_trailing_slash = TokenReviewVerifier(
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
        with patch("pathlib.Path.exists", return_value=True):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443",
                ca_cert_path="/custom/ca.crt",
            )
            assert verifier.ca_cert_path == "/custom/ca.crt"

    def test_ca_cert_path_explicit_not_exists(self) -> None:
        """Test explicit CA certificate path that doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443",
                ca_cert_path="/nonexistent/ca.crt",
            )
            assert verifier.ca_cert_path is None

    def test_ca_cert_path_auto_detect_in_cluster(self) -> None:
        """Test auto-detection of in-cluster CA certificate."""

        def mock_exists(self: object) -> bool:
            return str(self) == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        with patch("pathlib.Path.exists", mock_exists):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert (
                verifier.ca_cert_path
                == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            )

    def test_ca_cert_path_no_cert_available(self) -> None:
        """Test when no CA certificate is available."""
        with patch("pathlib.Path.exists", return_value=False):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert verifier.ca_cert_path is None
