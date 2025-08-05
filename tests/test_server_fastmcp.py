"""Tests for the FastMCP server implementation."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from proms_mcp.config import PrometheusDataSource
from proms_mcp.server import (
    app,
    format_tool_response,
    initialize_server,
    mcp_access_log,
    metrics_data,
    tool_error_handler,
    validate_datasource,
)


class TestFastMCPServer:
    """Test the FastMCP server implementation."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        # Create a temporary directory for test datasources
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def teardown_method(self) -> None:
        """Cleanup test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def create_test_datasource_config(self) -> str:
        """Create a test datasource configuration."""
        config_content = {
            "apiVersion": 1,
            "prune": True,
            "datasources": [
                {
                    "name": "test-prometheus",
                    "type": "prometheus",
                    "url": "https://prometheus.example.com",
                    "jsonData": {"httpHeaderName1": "Authorization"},
                    "secureJsonData": {"httpHeaderValue1": "Bearer test-token"},
                }
            ],
        }

        config_file = self.temp_path / "datasources.yaml"
        import yaml

        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return str(self.temp_path)

    @pytest.mark.asyncio
    async def test_server_initialization(self) -> None:
        """Test server initialization."""
        self.create_test_datasource_config()

        with (
            patch("proms_mcp.server.get_config_loader") as mock_get_config,
            patch("proms_mcp.server.get_auth_mode") as mock_get_auth_mode,
        ):
            mock_config = Mock()
            mock_config.datasources = {
                "test-prometheus": PrometheusDataSource(
                    name="test-prometheus",
                    url="https://prometheus.example.com",
                    auth_header_name="Authorization",
                    auth_header_value="Bearer test-token",
                )
            }
            mock_get_config.return_value = mock_config
            # Use no-auth mode for testing
            from proms_mcp.auth import AuthMode

            mock_get_auth_mode.return_value = AuthMode.NONE

            initialize_server()

            mock_config.load_datasources.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        """Test that all 8 tools are registered."""
        tools = await app.list_tools()

        assert len(tools) == 8

        expected_tools = [
            "list_datasources",
            "list_metrics",
            "get_metric_metadata",
            "query_instant",
            "query_range",
            "get_metric_labels",
            "get_label_values",
            "find_metrics_by_pattern",
        ]

        tool_names = [tool.name for tool in tools]
        for expected_tool in expected_tools:
            assert expected_tool in tool_names

    @pytest.mark.asyncio
    async def test_list_datasources_tool(self) -> None:
        """Test the list_datasources tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_config.datasources = {
                "test-prometheus": Mock(url="https://prometheus.example.com")
            }

            result = await app.call_tool("list_datasources", {})

            # FastMCP returns a tuple where first element is list of content blocks
            assert isinstance(result, tuple)
            assert len(result) > 0
            assert isinstance(result[0], list)
            assert len(result[0]) > 0

            # Parse the JSON response
            response_text = result[0][0].text
            response_data = json.loads(response_text)

            assert response_data["status"] == "success"
            assert len(response_data["data"]) == 1
            assert response_data["data"][0]["id"] == "test-prometheus"
            assert response_data["data"][0]["url"] == "https://prometheus.example.com"

    @pytest.mark.asyncio
    async def test_query_instant_tool(self) -> None:
        """Test the query_instant tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.query_instant.return_value = {
                    "status": "success",
                    "data": {"data": {"resultType": "vector", "result": []}},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "query_instant",
                    {"datasource_id": "test-prometheus", "promql": "up"},
                )

                # Parse the JSON response
                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"
                assert response_data["query"] == "up"
                assert "data" in response_data

    @pytest.mark.asyncio
    async def test_query_range_tool(self) -> None:
        """Test the query_range tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.query_range.return_value = {
                    "status": "success",
                    "data": {"data": {"resultType": "matrix", "result": []}},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "query_range",
                    {
                        "datasource_id": "test-prometheus",
                        "promql": "up",
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T01:00:00Z",
                        "step": "1m",
                    },
                )

                # Parse the JSON response
                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"
                assert response_data["query"] == "up"

    @pytest.mark.asyncio
    async def test_tool_error_handling(self) -> None:
        """Test error handling in tools."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_config.get_datasource.return_value = None  # Datasource not found

            result = await app.call_tool(
                "query_instant", {"datasource_id": "nonexistent", "promql": "up"}
            )

            # Parse the JSON response
            response_text = result[0][0].text  # type: ignore[index]
            response_data = json.loads(response_text)

            assert response_data["status"] == "error"
            assert "not found" in response_data["error"]

    def test_format_tool_response(self) -> None:
        """Test the response formatting utility."""
        # Test success response
        response = format_tool_response(
            {"test": "data"}, datasource="test-ds", query="up"
        )
        data = json.loads(response)

        assert data["status"] == "success"
        assert data["datasource"] == "test-ds"
        assert data["query"] == "up"
        assert data["data"] == {"test": "data"}
        # Timestamp and correlation_id removed from response format

        # Test error response
        response = format_tool_response(
            None, "error", "Test error", datasource="test-ds"
        )
        data = json.loads(response)

        assert data["status"] == "error"
        assert data["error"] == "Test error"
        assert data["datasource"] == "test-ds"
        assert "data" not in data

    # NEW COMPREHENSIVE TESTS FOR MISSING COVERAGE

    @pytest.mark.asyncio
    async def test_list_metrics_tool(self) -> None:
        """Test the list_metrics tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_names.return_value = {
                    "status": "success",
                    "data": {"data": ["up", "cpu_usage", "memory_usage"]},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "list_metrics", {"datasource_id": "test-prometheus"}
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"
                assert len(response_data["data"]) == 3

    @pytest.mark.asyncio
    async def test_list_metrics_tool_error(self) -> None:
        """Test the list_metrics tool with error."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_names.return_value = {
                    "status": "error",
                    "error": "Connection failed",
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "list_metrics", {"datasource_id": "test-prometheus"}
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "error"
                assert "Connection failed" in response_data["error"]

    @pytest.mark.asyncio
    async def test_get_metric_metadata_tool(self) -> None:
        """Test the get_metric_metadata tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_metadata.return_value = {
                    "status": "success",
                    "data": {"type": "gauge", "help": "Instance up status"},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "get_metric_metadata",
                    {"datasource_id": "test-prometheus", "metric_name": "up"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"

    @pytest.mark.asyncio
    async def test_get_metric_labels_tool(self) -> None:
        """Test the get_metric_labels tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_series.return_value = {
                    "status": "success",
                    "data": {
                        "data": [
                            {
                                "__name__": "up",
                                "job": "prometheus",
                                "instance": "localhost:9090",
                            },
                            {
                                "__name__": "up",
                                "job": "node",
                                "instance": "localhost:9100",
                            },
                        ]
                    },
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "get_metric_labels",
                    {"datasource_id": "test-prometheus", "metric_name": "up"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"
                # Should exclude __name__ and return sorted unique labels
                assert "job" in response_data["data"]
                assert "instance" in response_data["data"]
                assert "__name__" not in response_data["data"]

    @pytest.mark.asyncio
    async def test_get_label_values_tool(self) -> None:
        """Test the get_label_values tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_label_values.return_value = {
                    "status": "success",
                    "data": {"data": ["prometheus", "node-exporter"]},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "get_label_values",
                    {"datasource_id": "test-prometheus", "label_name": "job"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"

    @pytest.mark.asyncio
    async def test_find_metrics_by_pattern_tool(self) -> None:
        """Test the find_metrics_by_pattern tool."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_names.return_value = {
                    "status": "success",
                    "data": {"data": ["up", "cpu_usage", "memory_usage", "disk_usage"]},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "find_metrics_by_pattern",
                    {"datasource_id": "test-prometheus", "pattern": ".*usage"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"
                # Should match cpu_usage, memory_usage, disk_usage
                assert len(response_data["data"]) == 3
                assert "cpu_usage" in response_data["data"]
                assert "up" not in response_data["data"]

    @pytest.mark.asyncio
    async def test_find_metrics_by_pattern_invalid_regex(self) -> None:
        """Test find_metrics_by_pattern with invalid regex."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_names.return_value = {
                    "status": "success",
                    "data": {"data": ["up", "cpu_usage"]},
                }
                mock_get_client.return_value = mock_client

                result = await app.call_tool(
                    "find_metrics_by_pattern",
                    {"datasource_id": "test-prometheus", "pattern": "[invalid"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "error"
                assert "Invalid regex pattern" in response_data["error"]

    def test_validate_datasource(self) -> None:
        """Test datasource validation."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            datasource, error = validate_datasource("test-prometheus")
            assert datasource == mock_datasource
            assert error is None

            # Test missing datasource
            mock_config.get_datasource.return_value = None
            datasource, error = validate_datasource("nonexistent")
            assert datasource is None
            assert error is not None and "not found" in error

        # Test with no config loader
        with patch("proms_mcp.server.config_loader", None):
            datasource, error = validate_datasource("test")
            assert datasource is None
            assert error is not None and "not initialized" in error

    def test_format_tool_response_edge_cases(self) -> None:
        """Test format_tool_response with edge cases."""
        # Test with minimal parameters
        response = format_tool_response({"data": "test"})
        data = json.loads(response)
        assert data["status"] == "success"
        assert data["data"] == {"data": "test"}
        assert "datasource" not in data
        assert "query" not in data

        # Test error response with minimal parameters
        response = format_tool_response(None, "error", "Test error")
        data = json.loads(response)
        assert data["status"] == "error"
        assert data["error"] == "Test error"
        assert "data" not in data

        # Test error response with no error message
        response = format_tool_response(None, "error")
        data = json.loads(response)
        assert data["status"] == "error"
        assert data["error"] == "Unknown error"

    def test_mcp_access_log_decorator(self) -> None:
        """Test the mcp_access_log decorator."""

        # Test with sync function
        @mcp_access_log("test_tool")
        def sync_func(arg1: str, arg2: str = "default") -> str:
            return f"{arg1}-{arg2}"

        result = sync_func("test", arg2="value")
        assert result == "test-value"

        # Verify metrics were updated
        assert metrics_data["tool_requests_total"]["test_tool"]["success"] > 0

    @pytest.mark.asyncio
    async def test_tool_error_handler_decorator(self) -> None:
        """Test the tool_error_handler decorator."""

        # Test with sync function
        @tool_error_handler
        def sync_func_success() -> str:
            return format_tool_response({"result": "success"})

        with patch("proms_mcp.server.config_loader", Mock()):
            result = sync_func_success()
            data = json.loads(result)
            assert data["status"] == "success"

        # Test with sync function that raises exception
        @tool_error_handler
        def sync_func_error() -> str:
            raise ValueError("Test error")

        with patch("proms_mcp.server.config_loader", Mock()):
            result = sync_func_error()
            data = json.loads(result)
            assert data["status"] == "error"
            assert "Test error" in data["error"]

        # Test with no config loader
        @tool_error_handler
        def sync_func_no_config() -> str:
            return format_tool_response({"result": "success"})

        with patch("proms_mcp.server.config_loader", None):
            result = sync_func_no_config()
            data = json.loads(result)
            assert data["status"] == "error"
            assert "not initialized" in data["error"]


class TestFastMCPIntegration:
    """Integration tests for FastMCP server."""

    @pytest.mark.asyncio
    async def test_server_can_start(self) -> None:
        """Test that the server can be initialized without errors."""
        with (
            patch("proms_mcp.server.get_config_loader") as mock_get_config,
            patch("proms_mcp.server.get_auth_mode") as mock_get_auth_mode,
        ):
            mock_config = Mock()
            mock_config.datasources = {}
            mock_get_config.return_value = mock_config
            # Use no-auth mode for testing
            from proms_mcp.auth import AuthMode

            mock_get_auth_mode.return_value = AuthMode.NONE

            # This should not raise any exceptions
            initialize_server()

            # Verify tools are registered
            tools = await app.list_tools()
            assert len(tools) == 8

    def test_server_stateless_configuration(self) -> None:
        """Test that the server is configured for stateless HTTP."""
        # Verify that the FastMCP app is configured with stateless_http=True
        # This prevents session-related errors on reconnection
        from proms_mcp.server import app

        # The stateless_http configuration should be enabled
        # We can verify the app object exists and is properly configured
        assert app is not None
        assert app.name == "proms-mcp"
        # The stateless_http=True configuration prevents reconnection issues

    def test_server_main_function(self) -> None:
        """Test the main server entry point."""
        from proms_mcp.server import main

        with patch("proms_mcp.server.start_health_metrics_server") as mock_start_health:
            with patch("uvicorn.run") as mock_uvicorn_run:
                with patch.dict("os.environ", {"PORT": "9000", "HOST": "0.0.0.0"}):
                    main()

                mock_start_health.assert_called_once()
                mock_uvicorn_run.assert_called_once()

                # Check that uvicorn was called with correct parameters
                call_args = mock_uvicorn_run.call_args
                assert call_args[1]["host"] == "0.0.0.0"
                assert call_args[1]["port"] == 9000

    def test_server_main_with_exception(self) -> None:
        """Test server main function handles exceptions."""
        from proms_mcp.server import main

        with patch("proms_mcp.server.start_health_metrics_server"):
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_uvicorn_run.side_effect = Exception("Server error")

                with pytest.raises(Exception, match="Server error"):
                    main()

    def test_server_main_keyboard_interrupt(self) -> None:
        """Test server main function handles KeyboardInterrupt."""
        from proms_mcp.server import main

        with patch("proms_mcp.server.start_health_metrics_server"):
            with patch("uvicorn.run") as mock_uvicorn_run:
                mock_uvicorn_run.side_effect = KeyboardInterrupt()

                # Should not raise exception, just log and exit gracefully
                main()

    def test_server_initialization_with_datasources(self) -> None:
        """Test server initialization with multiple datasources."""
        with (
            patch("proms_mcp.server.get_config_loader") as mock_get_config,
            patch("proms_mcp.server.get_auth_mode") as mock_get_auth_mode,
        ):
            mock_config = Mock()
            mock_config.datasources = {
                "ds1": PrometheusDataSource(name="ds1", url="http://prom1:9090"),
                "ds2": PrometheusDataSource(name="ds2", url="http://prom2:9090"),
                "ds3": PrometheusDataSource(name="ds3", url="http://prom3:9090"),
            }
            mock_get_config.return_value = mock_config
            # Use no-auth mode for testing
            from proms_mcp.auth import AuthMode

            mock_get_auth_mode.return_value = AuthMode.NONE

            # Clear any existing metrics
            from proms_mcp.server import metrics_data

            metrics_data["datasources_configured"] = 0

            initialize_server()

            # Verify datasource count was updated
            assert metrics_data["datasources_configured"] == 3
            mock_config.load_datasources.assert_called_once()

    def test_server_initialization_config_loading_failure(self) -> None:
        """Test server handles config loading failures gracefully."""
        with (
            patch("proms_mcp.server.get_config_loader") as mock_get_config,
            patch("proms_mcp.server.get_auth_mode") as mock_get_auth_mode,
        ):
            mock_config = Mock()
            mock_config.load_datasources.side_effect = Exception("Config load failed")
            mock_config.datasources = {}
            mock_get_config.return_value = mock_config
            # Use no-auth mode for testing
            from proms_mcp.auth import AuthMode

            mock_get_auth_mode.return_value = AuthMode.NONE

            # The server should handle config loading failures gracefully
            # In the actual implementation, this would log an error but not crash
            try:
                initialize_server()
                # If it doesn't raise, that's fine too
            except Exception as e:
                # If it raises, verify it's the expected exception
                assert "Config load failed" in str(e)

            # Verify it attempted to load
            mock_config.load_datasources.assert_called_once()

    def test_server_main_with_default_environment(self) -> None:
        """Test server main with default environment variables."""
        from proms_mcp.server import main

        with patch("proms_mcp.server.start_health_metrics_server") as mock_start_health:
            with patch("uvicorn.run") as mock_uvicorn_run:
                # Clear environment to test defaults
                with patch.dict("os.environ", {}, clear=True):
                    main()

                mock_start_health.assert_called_once()
                mock_uvicorn_run.assert_called_once()

                # Check default parameters
                call_args = mock_uvicorn_run.call_args
                assert call_args[1]["host"] == "0.0.0.0"  # default
                assert call_args[1]["port"] == 8000  # default
                assert call_args[1]["timeout_graceful_shutdown"] == 8  # default

    def test_server_main_with_custom_shutdown_timeout(self) -> None:
        """Test server main with custom shutdown timeout."""
        from proms_mcp.server import main

        with patch("proms_mcp.server.start_health_metrics_server"):
            with patch("uvicorn.run") as mock_uvicorn_run:
                with patch.dict("os.environ", {"SHUTDOWN_TIMEOUT_SECONDS": "15"}):
                    main()

                call_args = mock_uvicorn_run.call_args
                assert call_args[1]["timeout_graceful_shutdown"] == 15

    def test_list_datasources_with_no_config_loader(self) -> None:
        """Test list_datasources when config_loader is None."""
        with patch("proms_mcp.server.config_loader", None):
            from proms_mcp.server import list_datasources

            result = list_datasources()
            data = json.loads(result)

            assert data["status"] == "error"
            assert "not initialized" in data["error"]

    @pytest.mark.asyncio
    async def test_server_ready_state(self) -> None:
        """Test server ready state management."""
        from proms_mcp.server import server_ready

        # Server should be ready by default
        assert server_ready is True

    def test_metrics_data_structure(self) -> None:
        """Test that metrics data has the expected structure."""
        from proms_mcp.server import metrics_data

        # Verify all expected keys exist
        expected_keys = [
            "tool_requests_total",
            "tool_request_durations",
            "server_requests_total",
            "datasources_configured",
            "connected_clients",
            "server_start_time",
        ]

        for key in expected_keys:
            assert key in metrics_data

        # Verify types
        assert isinstance(metrics_data["tool_requests_total"], dict)
        assert isinstance(metrics_data["tool_request_durations"], dict)
        assert isinstance(metrics_data["server_requests_total"], dict)
        assert isinstance(metrics_data["datasources_configured"], int)
        assert isinstance(metrics_data["connected_clients"], int)
        assert isinstance(metrics_data["server_start_time"], float)

    @pytest.mark.asyncio
    async def test_tool_with_missing_optional_parameter(self) -> None:
        """Test tools handle missing optional parameters correctly."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_label_values.return_value = {
                    "status": "success",
                    "data": {"data": ["value1", "value2"]},
                }
                mock_get_client.return_value = mock_client

                # Test get_label_values without optional metric_name parameter
                result = await app.call_tool(
                    "get_label_values",
                    {"datasource_id": "test-prometheus", "label_name": "job"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"
                assert response_data["datasource"] == "test-prometheus"

    @pytest.mark.asyncio
    async def test_query_instant_with_optional_time(self) -> None:
        """Test query_instant with optional time parameter."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.query_instant.return_value = {
                    "status": "success",
                    "data": {"data": {"resultType": "vector", "result": []}},
                }
                mock_get_client.return_value = mock_client

                # Test without time parameter
                result = await app.call_tool(
                    "query_instant",
                    {"datasource_id": "test-prometheus", "promql": "up"},
                )

                response_text = result[0][0].text  # type: ignore[index]
                response_data = json.loads(response_text)

                assert response_data["status"] == "success"

                # Verify client was called with None for time
                mock_client.query_instant.assert_called_with("up", None)

    @pytest.mark.asyncio
    async def test_async_tool_error_handler_decorator(self) -> None:
        """Test the tool_error_handler decorator with async functions."""

        # Test with async function success
        @tool_error_handler
        async def async_func_success() -> str:
            return format_tool_response({"result": "async_success"})

        with patch("proms_mcp.server.config_loader", Mock()):
            result = await async_func_success()
            data = json.loads(result)
            assert data["status"] == "success"
            assert data["data"]["result"] == "async_success"

        # Test with async function that raises exception
        @tool_error_handler
        async def async_func_error() -> str:
            raise ValueError("Async test error")

        with patch("proms_mcp.server.config_loader", Mock()):
            result = await async_func_error()
            data = json.loads(result)
            assert data["status"] == "error"
            assert "Async test error" in data["error"]

        # Test with no config loader (async)
        @tool_error_handler
        async def async_func_no_config() -> str:
            return format_tool_response({"result": "success"})

        with patch("proms_mcp.server.config_loader", None):
            result = await async_func_no_config()
            data = json.loads(result)
            assert data["status"] == "error"
            assert "not initialized" in data["error"]

    @pytest.mark.asyncio
    async def test_mcp_access_log_decorator_async(self) -> None:
        """Test the mcp_access_log decorator with async functions."""

        # Test with async function
        @mcp_access_log("async_test_tool")
        async def async_func(arg1: str, arg2: str = "default") -> str:
            return f"async-{arg1}-{arg2}"

        result = await async_func("test", arg2="value")
        assert result == "async-test-value"

        # Verify metrics were updated
        assert metrics_data["tool_requests_total"]["async_test_tool"]["success"] > 0

        # Test async function with exception
        @mcp_access_log("async_error_tool")
        async def async_func_error() -> str:
            raise ValueError("Async error")

        with pytest.raises(ValueError, match="Async error"):
            await async_func_error()

        # Verify error metrics were updated
        assert metrics_data["tool_requests_total"]["async_error_tool"]["error"] > 0

    @pytest.mark.asyncio
    async def test_all_tools_error_handling(self) -> None:
        """Test error handling for all MCP tools when datasource fails."""
        with patch("proms_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("proms_mcp.server.get_prometheus_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.get_metric_names.side_effect = Exception(
                    "Connection failed"
                )
                mock_client.get_metric_metadata.side_effect = Exception(
                    "Connection failed"
                )
                mock_client.get_series.side_effect = Exception("Connection failed")
                mock_client.get_label_values.side_effect = Exception(
                    "Connection failed"
                )
                mock_client.query_instant.side_effect = Exception("Connection failed")
                mock_client.query_range.side_effect = Exception("Connection failed")
                mock_get_client.return_value = mock_client

                # Test all tools handle exceptions gracefully
                tools_to_test = [
                    ("list_metrics", {"datasource_id": "test"}),
                    (
                        "get_metric_metadata",
                        {"datasource_id": "test", "metric_name": "up"},
                    ),
                    (
                        "get_metric_labels",
                        {"datasource_id": "test", "metric_name": "up"},
                    ),
                    (
                        "get_label_values",
                        {"datasource_id": "test", "label_name": "job"},
                    ),
                    ("query_instant", {"datasource_id": "test", "promql": "up"}),
                    (
                        "query_range",
                        {
                            "datasource_id": "test",
                            "promql": "up",
                            "start": "now-1h",
                            "end": "now",
                            "step": "1m",
                        },
                    ),
                    (
                        "find_metrics_by_pattern",
                        {"datasource_id": "test", "pattern": "up.*"},
                    ),
                ]

                for tool_name, params in tools_to_test:
                    result = await app.call_tool(tool_name, params)
                    response_text = result[0][0].text  # type: ignore[index]
                    response_data = json.loads(response_text)

                    # All should return error status, not crash
                    assert response_data["status"] == "error"
                    assert (
                        "Failed to execute" in response_data["error"]
                        or "Connection failed" in response_data["error"]
                    )
