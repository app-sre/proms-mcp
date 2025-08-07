"""Health and metrics monitoring endpoints for the MCP server."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import structlog

logger = structlog.get_logger()


class HealthMetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for health and metrics endpoints."""

    def __init__(self, *args: Any, metrics_data: dict[str, Any], **kwargs: Any):
        self.metrics_data = metrics_data
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Handle GET requests for health and metrics endpoints."""
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self._handle_not_found()

    def _handle_health(self) -> None:
        """Handle health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        health_data = get_health_data(self.metrics_data)
        self.wfile.write(json.dumps(health_data).encode())

        # Update server request metrics
        self.metrics_data["server_requests_total"]["GET"]["/health"] += 1

    def _handle_metrics(self) -> None:
        """Handle metrics endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

        metrics_text = get_prometheus_metrics(self.metrics_data)
        self.wfile.write(metrics_text.encode())

        # Update server request metrics
        self.metrics_data["server_requests_total"]["GET"]["/metrics"] += 1

    def _handle_not_found(self) -> None:
        """Handle 404 responses."""
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server logging."""
        pass


def get_health_data(metrics_data: dict[str, Any]) -> dict[str, Any]:
    """Get server health status."""
    return {
        "status": "healthy",  # Could be made dynamic based on server state
        "uptime_seconds": time.time() - metrics_data["server_start_time"],
        "datasources_configured": metrics_data["datasources_configured"],
        "connected_clients": metrics_data["connected_clients"],
    }


def get_prometheus_metrics(metrics_data: dict[str, Any]) -> str:
    """Generate Prometheus metrics format."""
    lines = []

    # MCP tool requests total
    lines.append(
        "# HELP proms_mcp_tool_requests_total Total number of MCP tool requests"
    )
    lines.append("# TYPE proms_mcp_tool_requests_total counter")
    for tool, statuses in metrics_data["tool_requests_total"].items():
        for status, count in statuses.items():
            lines.append(
                f'proms_mcp_tool_requests_total{{tool="{tool}",status="{status}"}} {count}'
            )

    # MCP tool request duration
    lines.append(
        "# HELP proms_mcp_tool_request_duration_seconds MCP tool request durations"
    )
    lines.append("# TYPE proms_mcp_tool_request_duration_seconds histogram")
    for tool, durations in metrics_data["tool_request_durations"].items():
        if durations:
            # Simple histogram buckets
            buckets = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0]
            counts = [0] * len(buckets)
            total_count = len(durations)
            total_sum = sum(d / 1000.0 for d in durations)  # Convert ms to seconds

            for duration_ms in durations:
                duration_s = duration_ms / 1000.0
                for i, bucket in enumerate(buckets):
                    if duration_s <= bucket:
                        counts[i] += 1

            # Cumulative counts for histogram
            cumulative = 0
            for i, (bucket, count) in enumerate(zip(buckets, counts)):
                cumulative += count
                lines.append(
                    f'proms_mcp_tool_request_duration_seconds_bucket{{tool="{tool}",le="{bucket}"}} {cumulative}'
                )

            lines.append(
                f'proms_mcp_tool_request_duration_seconds_bucket{{tool="{tool}",le="+Inf"}} {total_count}'
            )
            lines.append(
                f'proms_mcp_tool_request_duration_seconds_count{{tool="{tool}"}} {total_count}'
            )
            lines.append(
                f'proms_mcp_tool_request_duration_seconds_sum{{tool="{tool}"}} {total_sum}'
            )

    # Server requests total
    lines.append("# HELP proms_mcp_server_requests_total Total number of HTTP requests")
    lines.append("# TYPE proms_mcp_server_requests_total counter")
    for method, endpoints in metrics_data["server_requests_total"].items():
        for endpoint, count in endpoints.items():
            lines.append(
                f'proms_mcp_server_requests_total{{method="{method}",endpoint="{endpoint}"}} {count}'
            )

    # Datasources configured
    lines.append(
        "# HELP proms_mcp_datasources_configured Number of configured Prometheus datasources"
    )
    lines.append("# TYPE proms_mcp_datasources_configured gauge")
    lines.append(
        f"proms_mcp_datasources_configured {metrics_data['datasources_configured']}"
    )

    # Connected clients
    lines.append("# HELP proms_mcp_connected_clients Number of connected MCP clients")
    lines.append("# TYPE proms_mcp_connected_clients gauge")
    lines.append(f"proms_mcp_connected_clients {metrics_data['connected_clients']}")

    return "\n".join(lines) + "\n"


def start_health_metrics_server(metrics_data: dict[str, Any]) -> None:
    """Start a simple HTTP server for health and metrics endpoints."""

    def handler_factory(*args: Any, **kwargs: Any) -> HealthMetricsHandler:
        """Factory function to create handler with metrics_data."""
        return HealthMetricsHandler(*args, metrics_data=metrics_data, **kwargs)

    def run_server() -> None:
        """Run the health and metrics HTTP server."""
        port = int(os.getenv("HEALTH_METRICS_PORT", "8080"))
        server = HTTPServer(("0.0.0.0", port), handler_factory)
        logger.info(f"Health and metrics server starting on port {port}")
        try:
            server.serve_forever()
        except Exception as e:
            logger.error(f"Health/metrics server error: {e}")
        finally:
            server.server_close()

    # Start in background thread
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
