"""Tests for the FastMCP server implementation."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from promesh_mcp.config import PrometheusDataSource
from promesh_mcp.server import app, format_tool_response, initialize_server


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

        with patch("promesh_mcp.server.get_config_loader") as mock_get_config:
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

            initialize_server()

            mock_config.load_datasources.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        """Test that all 9 tools are registered."""
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
        with patch("promesh_mcp.server.config_loader") as mock_config:
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
        with patch("promesh_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("promesh_mcp.server.get_prometheus_client") as mock_get_client:
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
        with patch("promesh_mcp.server.config_loader") as mock_config:
            mock_datasource = Mock()
            mock_config.get_datasource.return_value = mock_datasource

            with patch("promesh_mcp.server.get_prometheus_client") as mock_get_client:
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
        with patch("promesh_mcp.server.config_loader") as mock_config:
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


class TestFastMCPIntegration:
    """Integration tests for FastMCP server."""

    @pytest.mark.asyncio
    async def test_server_can_start(self) -> None:
        """Test that the server can be initialized without errors."""
        with patch("promesh_mcp.server.get_config_loader") as mock_get_config:
            mock_config = Mock()
            mock_config.datasources = {}
            mock_get_config.return_value = mock_config

            # This should not raise any exceptions
            initialize_server()

            # Verify tools are registered
            tools = await app.list_tools()
            assert len(tools) == 8
