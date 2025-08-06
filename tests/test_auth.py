"""Tests for authentication functionality."""

import json
import os
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastmcp.server.auth.auth import AccessToken

from proms_mcp.auth import AuthMode, TokenReviewVerifier, User
from proms_mcp.config import get_auth_mode


# User model tests
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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": "success"}'  # Mock content for logging
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": "success"}'
            mock_response.json.return_value = mock_successful_tokenreview_response
            mock_client.post.return_value = mock_response

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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": {"authenticated": false}}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": {"authenticated": false}}'
            mock_response.json.return_value = mock_failed_tokenreview_response
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_api_error(self, verifier: TokenReviewVerifier) -> None:
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
            mock_client.post.return_value = mock_response

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_timeout(self, verifier: TokenReviewVerifier) -> None:
        """Test token verification with timeout."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.post.side_effect = httpx.TimeoutException("Request timed out")

            access_token = await verifier.verify_token(token)

            assert access_token is None

    @pytest.mark.asyncio
    async def test_verify_token_http_error(self, verifier: TokenReviewVerifier) -> None:
        """Test token verification with HTTP error."""
        token = "some-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b"invalid json"
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = "invalid json"
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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": "success"}'  # Mock content for logging
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": "success"}'
            mock_response.json.return_value = mock_successful_tokenreview_response
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token, "test-correlation-id")

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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": {"authenticated": true}}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": {"authenticated": true}}'
            mock_response.json.return_value = response_without_user
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token, "test-correlation-id")

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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = (
                b'{"status": {"authenticated": true, "user": {"username": "testuser"}}}'
            )
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = (
                '{"status": {"authenticated": true, "user": {"username": "testuser"}}}'
            )
            mock_response.json.return_value = response_partial_user
            mock_client.post.return_value = mock_response

            user = await verifier._validate_token_identity(token, "test-correlation-id")

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

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": {"authenticated": false}}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": {"authenticated": false}}'
            mock_response.json.return_value = {"status": {"authenticated": False}}
            mock_client.post.return_value = mock_response

            await verifier._validate_token_identity(token, "test-correlation-id")

            # Verify client was created with correct timeout and verify settings
            mock_client_class.assert_called_once_with(timeout=10.0, verify=True)

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
        with patch("proms_mcp.auth.Path.exists", return_value=True):
            verifier = TokenReviewVerifier(
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
                TokenReviewVerifier(
                    api_url="https://api.cluster.example.com:6443",
                    ca_cert_path="/nonexistent/ca.crt",
                )

    @pytest.mark.asyncio
    async def test_tls_verification_always_enabled(self) -> None:
        """Test that TLS verification is always enabled - never disabled."""
        verifier = TokenReviewVerifier(
            api_url="https://api.cluster.example.com:6443",
            ca_cert_path=None,  # No explicit CA cert
        )
        token = "test-token"

        with patch("proms_mcp.auth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": {"authenticated": true}}'
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = '{"status": {"authenticated": true}}'
            mock_response.json.return_value = {"status": {"authenticated": False}}
            mock_client.post.return_value = mock_response

            await verifier._validate_token_identity(token, "test-correlation-id")

            # Verify TLS verification is enabled (verify=True for system CA store)
            mock_client_class.assert_called_once_with(timeout=10.0, verify=True)

    def test_ca_cert_path_auto_detect_in_cluster(self) -> None:
        """Test auto-detection of in-cluster CA certificate."""

        def mock_exists(self: object) -> bool:
            return str(self) == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        with patch("proms_mcp.auth.Path.exists", mock_exists):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert (
                verifier.ca_cert_path
                == "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            )

    def test_ca_cert_path_no_cert_available(self) -> None:
        """Test when no CA certificate is available."""
        with patch("proms_mcp.auth.Path.exists", return_value=False):
            verifier = TokenReviewVerifier(
                api_url="https://api.cluster.example.com:6443", ca_cert_path=None
            )
            assert verifier.ca_cert_path is None
