"""Integration tests for authentication scenarios."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, mock_open, patch

import httpx
import pytest

from proms_mcp.auth.backends import NoAuthBackend
from proms_mcp.auth.models import User
from proms_mcp.auth.openshift import BearerTokenBackend, OpenShiftClient


class TestNoAuthScenario:
    """Test no authentication scenario."""

    @pytest.mark.asyncio
    async def test_no_auth_mode(self) -> None:
        """Test no authentication mode allows all requests."""
        backend = NoAuthBackend()
        mock_request = Mock()
        mock_request.headers = {}

        user = await backend.authenticate(mock_request)

        assert user is not None
        assert user.username == "dev-user"
        assert user.uid == "dev-user-id"
        assert "developers" in user.groups
        assert user.auth_method == "none"

    @pytest.mark.asyncio
    async def test_no_auth_ignores_headers(self) -> None:
        """Test no auth mode ignores any authorization headers."""
        backend = NoAuthBackend()
        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer some-token"}

        user = await backend.authenticate(mock_request)

        assert user is not None
        assert user.auth_method == "none"
        # Should still return dev user regardless of headers


class TestBearerTokenAuthScenarios:
    """Test bearer token authentication scenarios."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.api_url = "https://api.cluster.example.com:6443"
        self.mock_user = User(
            username="testuser", uid="user-123", groups=["developers"], auth_method="active"
        )

    @pytest.mark.asyncio
    async def test_bearer_token_no_ssl_verify(self) -> None:
        """Test bearer token authentication with SSL verification disabled."""
        with patch.dict("os.environ", {"OPENSHIFT_SSL_VERIFY": "false"}):
            client = OpenShiftClient(self.api_url)
            backend = BearerTokenBackend(client)

            # Mock successful API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "metadata": {"name": "testuser", "uid": "user-123"},
                "groups": ["developers"],
            }

            with patch("httpx.AsyncClient") as mock_client:
                mock_async_client = mock_client.return_value.__aenter__.return_value
                mock_async_client.get = AsyncMock(return_value=mock_response)

                # Test authentication
                request = Mock()
                request.headers = {"Authorization": "Bearer valid-token"}

                user = await backend.authenticate(request)

                assert user is not None
                assert user.username == "testuser"
                assert user.auth_method == "active"

                # Verify SSL verification was disabled
                mock_client.assert_called_once()
                call_args = mock_client.call_args
                assert call_args[1]["verify"] is False

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_public_cert(self) -> None:
        """Test bearer token auth with SSL verify using public cert (no CA cert param)."""
        # Default behavior - no OPENSHIFT_SSL_VERIFY env var, no custom CA cert
        client = OpenShiftClient(self.api_url)
        backend = BearerTokenBackend(client)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"name": "testuser", "uid": "user-123"},
            "groups": ["developers"],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = mock_client.return_value.__aenter__.return_value
            mock_async_client.get = AsyncMock(return_value=mock_response)

            request = Mock()
            request.headers = {"Authorization": "Bearer valid-token"}

            user = await backend.authenticate(request)

            assert user is not None
            assert user.username == "testuser"

            # Verify SSL verification uses system CA bundle (True)
            mock_client.assert_called_once()
            call_args = mock_client.call_args
            assert call_args[1]["verify"] is True

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_custom_cert(self) -> None:
        """Test bearer token auth with SSL verify using custom CA certificate."""
        # Create a temporary CA certificate file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as temp_ca:
            temp_ca.write("-----BEGIN CERTIFICATE-----\nfake cert content\n-----END CERTIFICATE-----")
            temp_ca_path = temp_ca.name

        try:
            with patch.dict("os.environ", {"OPENSHIFT_CA_CERT_PATH": temp_ca_path}):
                client = OpenShiftClient(self.api_url)
                backend = BearerTokenBackend(client)

                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "metadata": {"name": "testuser", "uid": "user-123"},
                    "groups": ["developers"],
                }

                with patch("httpx.AsyncClient") as mock_client:
                    mock_async_client = mock_client.return_value.__aenter__.return_value
                    mock_async_client.get = AsyncMock(return_value=mock_response)

                    request = Mock()
                    request.headers = {"Authorization": "Bearer valid-token"}

                    user = await backend.authenticate(request)

                    assert user is not None
                    assert user.username == "testuser"

                    # Verify SSL verification uses custom CA certificate
                    mock_client.assert_called_once()
                    call_args = mock_client.call_args
                    assert call_args[1]["verify"] == temp_ca_path
        finally:
            # Clean up temporary file
            os.unlink(temp_ca_path)

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_custom_cert_missing(self) -> None:
        """Test bearer token auth when custom CA cert path is set but file doesn't exist."""
        with patch.dict("os.environ", {"OPENSHIFT_CA_CERT_PATH": "/nonexistent/ca.crt"}):
            client = OpenShiftClient(self.api_url)
            backend = BearerTokenBackend(client)

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "metadata": {"name": "testuser", "uid": "user-123"},
                "groups": ["developers"],
            }

            with patch("httpx.AsyncClient") as mock_client:
                mock_async_client = mock_client.return_value.__aenter__.return_value
                mock_async_client.get = AsyncMock(return_value=mock_response)

                request = Mock()
                request.headers = {"Authorization": "Bearer valid-token"}

                user = await backend.authenticate(request)

                assert user is not None
                assert user.username == "testuser"

                # Should fall back to system CA bundle when custom cert doesn't exist
                mock_client.assert_called_once()
                call_args = mock_client.call_args
                assert call_args[1]["verify"] is True

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_from_pod_internal_api(self) -> None:
        """Test bearer token auth from pod using internal OpenShift API and mounted CA cert."""
        # Simulate in-pod environment
        internal_api_url = "https://kubernetes.default.svc:443"
        pod_ca_cert_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        pod_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"

        # Create temporary files to simulate pod-mounted files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_ca_path = os.path.join(temp_dir, "ca.crt")
            temp_token_path = os.path.join(temp_dir, "token")

            # Create mock CA cert file
            with open(temp_ca_path, 'w') as f:
                f.write("-----BEGIN CERTIFICATE-----\nmock CA cert\n-----END CERTIFICATE-----")

            # Create mock service account token file
            with open(temp_token_path, 'w') as f:
                f.write("mock-service-account-token")

            # Test with pod-like configuration
            client = OpenShiftClient(
                api_url=internal_api_url,
                service_account_token_path=temp_token_path,
                ca_cert_path=temp_ca_path
            )
            backend = BearerTokenBackend(client)

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "metadata": {"name": "pod-user", "uid": "pod-123"},
                "groups": ["system:serviceaccounts"],
            }

            with patch("httpx.AsyncClient") as mock_client:
                mock_async_client = mock_client.return_value.__aenter__.return_value
                mock_async_client.get = AsyncMock(return_value=mock_response)

                request = Mock()
                request.headers = {"Authorization": "Bearer user-token"}

                user = await backend.authenticate(request)

                assert user is not None
                assert user.username == "pod-user"
                assert "system:serviceaccounts" in user.groups

                # Verify it uses the pod's CA certificate
                mock_client.assert_called_once()
                call_args = mock_client.call_args
                assert call_args[1]["verify"] == temp_ca_path

                # Verify it uses the internal API URL
                mock_async_client.get.assert_called_once()
                get_call_args = mock_async_client.get.call_args
                assert internal_api_url in get_call_args[0][0]  # URL contains internal API

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_from_pod_default_paths(self) -> None:
        """Test bearer token auth from pod using default Kubernetes paths."""
        # Use default pod paths
        client = OpenShiftClient("https://kubernetes.default.svc:443")
        backend = BearerTokenBackend(client)

        # Mock the service account token file
        with patch("builtins.open", mock_open(read_data="pod-service-account-token")):
            # Mock successful token validation
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "metadata": {"name": "system:serviceaccount:default:myapp", "uid": "sa-123"},
                "groups": ["system:serviceaccounts", "system:serviceaccounts:default"],
            }

            with patch("httpx.AsyncClient") as mock_client:
                mock_async_client = mock_client.return_value.__aenter__.return_value
                mock_async_client.get = AsyncMock(return_value=mock_response)

                request = Mock()
                request.headers = {"Authorization": "Bearer user-bearer-token"}

                user = await backend.authenticate(request)

                assert user is not None
                assert user.username == "system:serviceaccount:default:myapp"
                assert "system:serviceaccounts" in user.groups

                # Verify API call was made with user token for validation
                mock_async_client.get.assert_called_once()
                call_args = mock_async_client.get.call_args
                assert call_args[1]["headers"]["Authorization"] == "Bearer user-bearer-token"

    @pytest.mark.asyncio
    async def test_bearer_token_ssl_verify_environment_variables(self) -> None:
        """Test SSL verification configuration with various environment variables."""
        test_cases = [
            ("false", False),
            ("true", True),
            ("", True),  # Default when not set
        ]

        for env_value, expected_verify in test_cases:
            with patch.dict("os.environ", {"OPENSHIFT_SSL_VERIFY": env_value}, clear=False):
                client = OpenShiftClient(self.api_url)
                ssl_config = client._get_ssl_verify_config()
                
                assert ssl_config == expected_verify, f"Failed for OPENSHIFT_SSL_VERIFY={env_value}"

    def test_ssl_verify_config_custom_ca_priority(self) -> None:
        """Test that custom CA cert takes priority over SSL verify env var."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as temp_ca:
            temp_ca.write("-----BEGIN CERTIFICATE-----\ntest cert\n-----END CERTIFICATE-----")
            temp_ca_path = temp_ca.name

        try:
            # Even with SSL_VERIFY=false, custom CA cert should be used
            with patch.dict("os.environ", {
                "OPENSHIFT_SSL_VERIFY": "false",
                "OPENSHIFT_CA_CERT_PATH": temp_ca_path
            }):
                client = OpenShiftClient(self.api_url)
                ssl_config = client._get_ssl_verify_config()
                
                # Should return the CA cert path, not False
                assert ssl_config == temp_ca_path
        finally:
            os.unlink(temp_ca_path)

    @pytest.mark.asyncio
    async def test_bearer_token_auth_failure_scenarios(self) -> None:
        """Test various authentication failure scenarios."""
        client = OpenShiftClient(self.api_url)
        backend = BearerTokenBackend(client)

        # Test network timeout
        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = mock_client.return_value.__aenter__.return_value
            mock_async_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

            request = Mock()
            request.headers = {"Authorization": "Bearer timeout-token"}

            user = await backend.authenticate(request)
            assert user is None

        # Test SSL certificate error
        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = mock_client.return_value.__aenter__.return_value
            mock_async_client.get = AsyncMock(
                side_effect=httpx.RequestError("SSL certificate verify failed")
            )

            request = Mock()
            request.headers = {"Authorization": "Bearer ssl-error-token"}

            user = await backend.authenticate(request)
            assert user is None

        # Test 403 Forbidden (insufficient permissions)
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 403
            mock_async_client = mock_client.return_value.__aenter__.return_value
            mock_async_client.get = AsyncMock(return_value=mock_response)

            request = Mock()
            request.headers = {"Authorization": "Bearer forbidden-token"}

            user = await backend.authenticate(request)
            assert user is None

    @pytest.mark.asyncio
    async def test_bearer_token_service_account_token_scenarios(self) -> None:
        """Test service account token handling in different scenarios."""
        # Test with environment variable
        with patch.dict("os.environ", {"OPENSHIFT_SERVICE_ACCOUNT_TOKEN": "env-sa-token"}):
            client = OpenShiftClient(self.api_url)
            token = client._get_service_account_token()
            assert token == "env-sa-token"

        # Test with file (when env var not set)
        with patch.dict("os.environ", {}, clear=True):
            with patch("builtins.open", mock_open(read_data="file-sa-token")):
                client = OpenShiftClient(self.api_url)
                token = client._get_service_account_token()
                assert token == "file-sa-token"

        # Test with missing file and no env var
        with patch.dict("os.environ", {}, clear=True):
            with patch("builtins.open", side_effect=FileNotFoundError()):
                client = OpenShiftClient(self.api_url)
                token = client._get_service_account_token()
                assert token == ""

        # Test that env var takes priority over file
        with patch.dict("os.environ", {"OPENSHIFT_SERVICE_ACCOUNT_TOKEN": "env-priority"}):
            with patch("builtins.open", mock_open(read_data="file-content")):
                client = OpenShiftClient(self.api_url)
                token = client._get_service_account_token()
                assert token == "env-priority"


class TestAuthenticationIntegration:
    """Integration tests combining different authentication scenarios."""

    @pytest.mark.asyncio
    async def test_auth_mode_switching(self) -> None:
        """Test switching between authentication modes."""
        # Test no auth mode
        no_auth_backend = NoAuthBackend()
        request = Mock()
        request.headers = {"Authorization": "Bearer some-token"}

        no_auth_user = await no_auth_backend.authenticate(request)
        assert no_auth_user is not None
        assert no_auth_user.auth_method == "none"

        # Test active auth mode
        client = OpenShiftClient("https://api.cluster.example.com:6443")
        bearer_backend = BearerTokenBackend(client)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metadata": {"name": "activeuser", "uid": "active-123"},
            "groups": ["admin"],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = mock_client.return_value.__aenter__.return_value
            mock_async_client.get = AsyncMock(return_value=mock_response)

            active_user = await bearer_backend.authenticate(request)
            assert active_user is not None
            assert active_user.auth_method == "active"
            assert active_user.username == "activeuser"

    @pytest.mark.asyncio
    async def test_pod_vs_external_api_scenarios(self) -> None:
        """Test authentication from pod vs external scenarios."""
        # External API scenario (public LetsEncrypt cert)
        external_client = OpenShiftClient("https://api.cluster.example.com:6443")
        external_backend = BearerTokenBackend(external_client)

        # Internal API scenario (pod with mounted CA)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.crt', delete=False) as temp_ca:
            temp_ca.write("-----BEGIN CERTIFICATE-----\ninternal CA\n-----END CERTIFICATE-----")
            temp_ca_path = temp_ca.name

        try:
            internal_client = OpenShiftClient(
                "https://kubernetes.default.svc:443",
                ca_cert_path=temp_ca_path
            )
            internal_backend = BearerTokenBackend(internal_client)

            # Mock responses for both scenarios
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "metadata": {"name": "testuser", "uid": "test-123"},
                "groups": ["developers"],
            }

            request = Mock()
            request.headers = {"Authorization": "Bearer test-token"}

            with patch("httpx.AsyncClient") as mock_client:
                mock_async_client = mock_client.return_value.__aenter__.return_value
                mock_async_client.get = AsyncMock(return_value=mock_response)

                # Test external API (should use system CA bundle)
                user1 = await external_backend.authenticate(request)
                assert user1 is not None

                # Test internal API (should use custom CA)
                user2 = await internal_backend.authenticate(request)
                assert user2 is not None

                # Verify different SSL configurations were used
                assert mock_client.call_count == 2
                calls = mock_client.call_args_list
                
                # First call (external) should use system CA (verify=True)
                assert calls[0][1]["verify"] is True
                
                # Second call (internal) should use custom CA
                assert calls[1][1]["verify"] == temp_ca_path

        finally:
            os.unlink(temp_ca_path) 
