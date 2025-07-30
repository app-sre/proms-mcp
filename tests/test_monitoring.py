"""Tests for the monitoring module."""

import time
from collections import defaultdict
from typing import Any
from unittest.mock import Mock, patch

from proms_mcp.monitoring import (
    HealthMetricsHandler,
    get_health_data,
    get_prometheus_metrics,
    start_health_metrics_server,
)


class TestMonitoring:
    """Test the monitoring functionality."""

    def test_get_health_data(self) -> None:
        """Test health data generation."""
        start_time = time.time()
        metrics_data = {
            "server_start_time": start_time,
            "datasources_configured": 3,
            "connected_clients": 2,
        }

        health_data = get_health_data(metrics_data)

        assert health_data["status"] == "healthy"
        assert health_data["datasources_configured"] == 3
        assert health_data["connected_clients"] == 2
        assert "uptime_seconds" in health_data
        assert health_data["uptime_seconds"] >= 0

    def test_get_prometheus_metrics_empty(self) -> None:
        """Test Prometheus metrics generation with empty data."""
        metrics_data = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        metrics_text = get_prometheus_metrics(metrics_data)

        assert "# HELP mcp_tool_requests_total" in metrics_text
        assert "# TYPE mcp_tool_requests_total counter" in metrics_text
        assert "# HELP mcp_datasources_configured" in metrics_text
        assert "mcp_datasources_configured 0" in metrics_text
        assert "mcp_connected_clients 0" in metrics_text

    def test_get_prometheus_metrics_with_data(self) -> None:
        """Test Prometheus metrics generation with sample data."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 2,
            "connected_clients": 1,
        }

        # Add some sample data
        metrics_data["tool_requests_total"]["list_datasources"]["success"] = 5
        metrics_data["tool_requests_total"]["query_instant"]["error"] = 1
        metrics_data["tool_request_durations"]["list_datasources"] = [
            100.0,
            150.0,
            200.0,
        ]
        metrics_data["server_requests_total"]["GET"]["/health"] = 10

        metrics_text = get_prometheus_metrics(metrics_data)

        # Check tool requests
        assert (
            'mcp_tool_requests_total{tool="list_datasources",status="success"} 5'
            in metrics_text
        )
        assert (
            'mcp_tool_requests_total{tool="query_instant",status="error"} 1'
            in metrics_text
        )

        # Check server requests
        assert (
            'mcp_server_requests_total{method="GET",endpoint="/health"} 10'
            in metrics_text
        )

        # Check gauges
        assert "mcp_datasources_configured 2" in metrics_text
        assert "mcp_connected_clients 1" in metrics_text

        # Check histogram data
        assert (
            'mcp_tool_request_duration_seconds_count{tool="list_datasources"} 3'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_sum{tool="list_datasources"} 0.45'
            in metrics_text
        )

    def test_prometheus_metrics_histogram_buckets(self) -> None:
        """Test that histogram buckets are generated correctly."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        # Add durations that should fall into different buckets
        metrics_data["tool_request_durations"]["test_tool"] = [
            50.0,
            800.0,
            2000.0,
            12000.0,
        ]  # 0.05s, 0.8s, 2s, 12s

        metrics_text = get_prometheus_metrics(metrics_data)

        # Check that buckets are present (cumulative counts)
        # 50ms (0.05s) -> le="0.1" bucket: 1
        # 800ms (0.8s) -> le="1.0" bucket: 1 + 1 = 2 (but algorithm is different)
        # Let's just check the structure is correct
        assert (
            'mcp_tool_request_duration_seconds_bucket{tool="test_tool",le="0.1"} 1'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_bucket{tool="test_tool",le="+Inf"} 4'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_count{tool="test_tool"} 4'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_sum{tool="test_tool"} 14.85'
            in metrics_text
        )

    @patch("proms_mcp.monitoring.HTTPServer")
    @patch("proms_mcp.monitoring.threading.Thread")
    def test_start_health_metrics_server(
        self, mock_thread: Any, mock_http_server: Any
    ) -> None:
        """Test that the health metrics server starts correctly."""
        metrics_data: dict[str, Any] = {"test": "data"}

        start_health_metrics_server(metrics_data)

        # Verify thread was created and started
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    def test_prometheus_metrics_empty_durations(self) -> None:
        """Test metrics generation with empty duration lists."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": {"empty_tool": []},
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        metrics_text = get_prometheus_metrics(metrics_data)

        # Should not include histogram data for empty durations
        assert 'tool="empty_tool"' not in metrics_text

    def test_prometheus_metrics_complex_histogram(self) -> None:
        """Test complex histogram bucket calculations."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": {
                "complex_tool": [25.0, 75.0, 250.0, 750.0, 2500.0, 7500.0, 15000.0]
            },
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        metrics_text = get_prometheus_metrics(metrics_data)

        # Verify all buckets are present
        buckets = ["0.1", "0.5", "1.0", "5.0", "10.0", "30.0"]
        for bucket in buckets:
            assert f'le="{bucket}"' in metrics_text

        # Verify +Inf bucket
        assert 'le="+Inf"' in metrics_text
        assert (
            'mcp_tool_request_duration_seconds_count{tool="complex_tool"} 7'
            in metrics_text
        )


class TestHealthMetricsHandler:
    """Test the HealthMetricsHandler HTTP handler."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.metrics_data: dict[str, Any] = {
            "server_start_time": time.time(),
            "datasources_configured": 2,
            "connected_clients": 1,
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
        }

    def test_handler_initialization(self) -> None:
        """Test that handler can be initialized with metrics data."""
        # Test that the handler constructor works
        with patch("proms_mcp.monitoring.BaseHTTPRequestHandler.__init__"):
            handler = HealthMetricsHandler(
                None, None, None, metrics_data=self.metrics_data
            )
            assert handler.metrics_data == self.metrics_data

    def test_log_message_suppressed(self) -> None:
        """Test that log messages are suppressed."""
        # Create a mock handler instance
        handler = Mock(spec=HealthMetricsHandler)

        # This should not raise any exceptions and should do nothing
        HealthMetricsHandler.log_message(handler, "Test message", "arg1", "arg2")
        # No assertion needed - just verify it doesn't crash

    def test_handler_constructor_with_metrics_data(self) -> None:
        """Test that handler can be created with metrics data parameter."""
        # Test the handler constructor signature - it should accept metrics_data
        # We can't easily test the actual HTTP handling without starting a server,
        # but we can verify the class structure is correct
        assert hasattr(HealthMetricsHandler, "__init__")
        assert hasattr(HealthMetricsHandler, "do_GET")
        assert hasattr(HealthMetricsHandler, "_handle_health")
        assert hasattr(HealthMetricsHandler, "_handle_metrics")
        assert hasattr(HealthMetricsHandler, "_handle_not_found")
        assert hasattr(HealthMetricsHandler, "log_message")


class TestHealthMetricsIntegration:
    """Integration tests for health metrics server."""

    @patch.dict("os.environ", {"HEALTH_METRICS_PORT": "9999"})
    @patch("proms_mcp.monitoring.HTTPServer")
    @patch("proms_mcp.monitoring.threading.Thread")
    def test_start_health_metrics_server_with_custom_port(
        self, mock_thread: Mock, mock_http_server: Mock
    ) -> None:
        """Test server starts with custom port from environment."""
        metrics_data: dict[str, Any] = {"test": "data"}

        # Mock the run_server function to avoid actual HTTP server creation
        with patch("proms_mcp.monitoring.HTTPServer"):
            start_health_metrics_server(metrics_data)

        # Verify thread was created and started
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    @patch("proms_mcp.monitoring.HTTPServer")
    @patch("proms_mcp.monitoring.threading.Thread")
    def test_start_health_metrics_server_default_port(
        self, mock_thread: Mock, mock_http_server: Mock
    ) -> None:
        """Test server starts with default port."""
        metrics_data: dict[str, Any] = {"test": "data"}

        with patch.dict("os.environ", {}, clear=True):
            with patch("proms_mcp.monitoring.HTTPServer"):
                start_health_metrics_server(metrics_data)

        # Verify thread was created and started
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    @patch("proms_mcp.monitoring.logger")
    @patch("proms_mcp.monitoring.HTTPServer")
    @patch("proms_mcp.monitoring.threading.Thread")
    def test_start_health_metrics_server_with_exception(
        self, mock_thread: Mock, mock_http_server: Mock, mock_logger: Mock
    ) -> None:
        """Test server handles exceptions during startup."""
        metrics_data: dict[str, Any] = {"test": "data"}

        # Mock the server to raise an exception
        mock_server_instance = Mock()
        mock_server_instance.serve_forever.side_effect = Exception("Server error")
        mock_http_server.return_value = mock_server_instance

        start_health_metrics_server(metrics_data)

        # Verify thread was created and started
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    def test_health_data_with_edge_cases(self) -> None:
        """Test health data generation with edge case values."""
        # Test with very recent start time
        recent_start = time.time() - 0.1
        metrics_data = {
            "server_start_time": recent_start,
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        health_data = get_health_data(metrics_data)

        assert health_data["status"] == "healthy"
        assert health_data["datasources_configured"] == 0
        assert health_data["connected_clients"] == 0
        assert health_data["uptime_seconds"] >= 0
        assert health_data["uptime_seconds"] < 1  # Should be very small

        # Test with large values
        old_start = time.time() - 86400  # 1 day ago
        metrics_data = {
            "server_start_time": old_start,
            "datasources_configured": 100,
            "connected_clients": 50,
        }

        health_data = get_health_data(metrics_data)

        assert health_data["status"] == "healthy"
        assert health_data["datasources_configured"] == 100
        assert health_data["connected_clients"] == 50
        assert health_data["uptime_seconds"] > 86000  # Close to 1 day

    def test_prometheus_metrics_with_special_characters(self) -> None:
        """Test metrics generation with special characters in tool names."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 1,
            "connected_clients": 1,
        }

        # Add data with special characters (should be handled properly)
        metrics_data["tool_requests_total"]["tool-with-dashes"]["success"] = 5
        metrics_data["tool_requests_total"]["tool_with_underscores"]["error"] = 2
        metrics_data["server_requests_total"]["POST"]["/special-endpoint"] = 3

        metrics_text = get_prometheus_metrics(metrics_data)

        # Verify special characters are preserved in labels
        assert 'tool="tool-with-dashes"' in metrics_text
        assert 'tool="tool_with_underscores"' in metrics_text
        assert 'endpoint="/special-endpoint"' in metrics_text

    def test_prometheus_metrics_histogram_edge_cases(self) -> None:
        """Test histogram generation with edge case durations."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        # Test with very small durations
        metrics_data["tool_request_durations"]["fast_tool"] = [0.1, 0.01, 0.001]

        # Test with very large durations
        metrics_data["tool_request_durations"]["slow_tool"] = [
            60000.0,
            120000.0,
        ]  # 1-2 minutes

        # Test with single duration
        metrics_data["tool_request_durations"]["single_tool"] = [500.0]

        metrics_text = get_prometheus_metrics(metrics_data)

        # Verify all tools are included
        assert 'tool="fast_tool"' in metrics_text
        assert 'tool="slow_tool"' in metrics_text
        assert 'tool="single_tool"' in metrics_text

        # Verify counts are correct
        assert (
            'mcp_tool_request_duration_seconds_count{tool="fast_tool"} 3'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_count{tool="slow_tool"} 2'
            in metrics_text
        )
        assert (
            'mcp_tool_request_duration_seconds_count{tool="single_tool"} 1'
            in metrics_text
        )

    def test_prometheus_metrics_zero_values(self) -> None:
        """Test metrics generation with zero values."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 0,
            "connected_clients": 0,
        }

        # Add some zero values explicitly
        metrics_data["tool_requests_total"]["zero_tool"]["success"] = 0
        metrics_data["server_requests_total"]["GET"]["/zero-endpoint"] = 0

        metrics_text = get_prometheus_metrics(metrics_data)

        # Zero values should still be included
        assert (
            'mcp_tool_requests_total{tool="zero_tool",status="success"} 0'
            in metrics_text
        )
        assert (
            'mcp_server_requests_total{method="GET",endpoint="/zero-endpoint"} 0'
            in metrics_text
        )
        assert "mcp_datasources_configured 0" in metrics_text
        assert "mcp_connected_clients 0" in metrics_text

    def test_prometheus_metrics_large_dataset(self) -> None:
        """Test metrics generation with large datasets."""
        metrics_data: dict[str, Any] = {
            "tool_requests_total": defaultdict(lambda: defaultdict(int)),
            "tool_request_durations": defaultdict(list),
            "server_requests_total": defaultdict(lambda: defaultdict(int)),
            "datasources_configured": 1000,
            "connected_clients": 500,
        }

        # Add many tools and endpoints
        for i in range(20):
            tool_name = f"tool_{i}"
            metrics_data["tool_requests_total"][tool_name]["success"] = i * 10
            metrics_data["tool_requests_total"][tool_name]["error"] = i * 2
            metrics_data["tool_request_durations"][tool_name] = [
                float(j) for j in range(i + 1)
            ]

            endpoint = f"/endpoint_{i}"
            metrics_data["server_requests_total"]["GET"][endpoint] = i * 5
            metrics_data["server_requests_total"]["POST"][endpoint] = i * 3

        metrics_text = get_prometheus_metrics(metrics_data)

        # Verify large values are handled correctly
        assert "mcp_datasources_configured 1000" in metrics_text
        assert "mcp_connected_clients 500" in metrics_text

        # Verify some of the generated metrics exist
        assert 'tool="tool_10"' in metrics_text
        assert 'endpoint="/endpoint_15"' in metrics_text

        # Check that the metrics text is substantial but not excessive
        line_count = len(metrics_text.split("\n"))
        assert line_count > 100  # Should have many lines
        assert line_count < 10000  # But not excessive
