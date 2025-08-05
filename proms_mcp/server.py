#!/usr/bin/env python3
"""Lean Proms MCP Server using FastMCP."""

import asyncio
import os
import re
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any

import structlog
from fastmcp import FastMCP

from .auth import AuthMode
from .auth.backends import NoAuthBackend
from .auth.openshift import BearerTokenBackend, OpenShiftClient
from .client import get_prometheus_client
from .config import ConfigLoader, get_auth_mode, get_config_loader
from .logging import configure_logging, get_uvicorn_log_config
from .monitoring import start_health_metrics_server

# Configure logging
configure_logging()
logger = structlog.get_logger()


# Initialize FastMCP server
# stateless_http=True prevents "No valid session ID provided" errors when clients
# like Cursor try to reconnect after server restarts
app: FastMCP = FastMCP(
    name="proms-mcp",
    instructions="A lean MCP server providing access to multiple Prometheus instances for metrics analysis and SRE operations.",
    stateless_http=True,
)

# Global readiness state for graceful shutdown
server_ready = True

# Global config loader
config_loader: ConfigLoader | None = None

# Global auth backend
auth_backend: Any = None

# Prometheus metrics collection
metrics_data: dict[str, Any] = {
    "tool_requests_total": defaultdict(
        lambda: defaultdict(int)
    ),  # tool -> status -> count
    "tool_request_durations": defaultdict(list),  # tool -> [duration_ms]
    "server_requests_total": defaultdict(
        lambda: defaultdict(int)
    ),  # method -> endpoint -> count
    "datasources_configured": 0,
    "connected_clients": 0,  # Track active connections
    "server_start_time": time.time(),
}


def mcp_access_log(tool_name: str) -> Callable:
    """Decorator to add access logging to MCP tools."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()

            # Extract datasource_id if present in kwargs
            datasource_id = kwargs.get("datasource_id", "N/A")

            # Log the request start
            logger.info(
                f"MCP tool called: {tool_name}",
                tool=tool_name,
                datasource=datasource_id,
                request_id=id(args),  # Simple request ID
            )

            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                duration_ms = round(duration * 1000, 2)

                # Log successful completion
                logger.info(
                    f"MCP tool completed: {tool_name}",
                    tool=tool_name,
                    datasource=datasource_id,
                    duration_ms=duration_ms,
                    status="success",
                    request_id=id(args),
                )

                # Update metrics
                metrics_data["tool_requests_total"][tool_name]["success"] += 1
                metrics_data["tool_request_durations"][tool_name].append(duration_ms)

                return result

            except Exception as e:
                duration = time.time() - start_time
                duration_ms = round(duration * 1000, 2)

                # Log error
                logger.error(
                    f"MCP tool failed: {tool_name}",
                    tool=tool_name,
                    datasource=datasource_id,
                    duration_ms=duration_ms,
                    status="error",
                    error=str(e),
                    error_type=type(e).__name__,
                    request_id=id(args),
                )

                # Update metrics
                metrics_data["tool_requests_total"][tool_name]["error"] += 1
                metrics_data["tool_request_durations"][tool_name].append(duration_ms)

                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()

            # Extract datasource_id if present in kwargs
            datasource_id = kwargs.get("datasource_id", "N/A")

            # Log the request start
            logger.info(
                f"MCP tool called: {tool_name}",
                tool=tool_name,
                datasource=datasource_id,
                request_id=id(args),  # Simple request ID
            )

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                duration_ms = round(duration * 1000, 2)

                # Log successful completion
                logger.info(
                    f"MCP tool completed: {tool_name}",
                    tool=tool_name,
                    datasource=datasource_id,
                    duration_ms=duration_ms,
                    status="success",
                    request_id=id(args),
                )

                # Update metrics
                metrics_data["tool_requests_total"][tool_name]["success"] += 1
                metrics_data["tool_request_durations"][tool_name].append(duration_ms)

                return result

            except Exception as e:
                duration = time.time() - start_time
                duration_ms = round(duration * 1000, 2)

                # Log error
                logger.error(
                    f"MCP tool failed: {tool_name}",
                    tool=tool_name,
                    datasource=datasource_id,
                    duration_ms=duration_ms,
                    status="error",
                    error=str(e),
                    error_type=type(e).__name__,
                    request_id=id(args),
                )

                # Update metrics
                metrics_data["tool_requests_total"][tool_name]["error"] += 1
                metrics_data["tool_request_durations"][tool_name].append(duration_ms)

                raise

        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def initialize_server() -> None:
    """Initialize the server with configuration."""
    global config_loader, auth_backend
    logger.info("Initializing Proms MCP server")

    # Initialize authentication
    auth_mode = get_auth_mode()
    logger.info(f"Authentication mode: {auth_mode.value}", auth_mode=auth_mode.value)

    if auth_mode == AuthMode.NONE:
        auth_backend = NoAuthBackend()
        logger.info("Using no-auth backend for development")
    elif auth_mode == AuthMode.ACTIVE:
        # Initialize OpenShift authentication
        openshift_api_url = os.getenv("OPENSHIFT_API_URL")
        if not openshift_api_url:
            logger.error("OPENSHIFT_API_URL required for active authentication mode")
            raise ValueError(
                "OPENSHIFT_API_URL environment variable is required for active authentication"
            )

        ca_cert_path = os.getenv("OPENSHIFT_CA_CERT_PATH")
        openshift_client = OpenShiftClient(openshift_api_url, ca_cert_path=ca_cert_path)
        auth_backend = BearerTokenBackend(openshift_client)
        logger.info(
            "Using OpenShift bearer token authentication", api_url=openshift_api_url
        )

    # Initialize datasources
    config_loader = get_config_loader()
    config_loader.load_datasources()
    logger.info(
        f"Loaded {len(config_loader.datasources)} datasources",
        datasource_count=len(config_loader.datasources),
    )

    # Update metrics
    metrics_data["datasources_configured"] = len(config_loader.datasources)
    # Log first few datasources as examples, not all of them
    sample_datasources = list(config_loader.datasources.items())[:3]
    for name, ds in sample_datasources:
        logger.info(f"Datasource example: {name}", datasource=name, url=ds.url)
    if len(config_loader.datasources) > 3:
        logger.info(
            f"... and {len(config_loader.datasources) - 3} more datasources",
        )
    logger.info("Server initialization complete")


def tool_error_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to handle common tool errors and server initialization checks."""

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            if not config_loader:
                return {
                    "status": "error",
                    "error": "Server not initialized",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            return await func(*args, **kwargs)  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Error in {func.__name__}", error=str(e), **kwargs)
            return {
                "status": "error",
                "error": f"Failed to execute {func.__name__}: {str(e)}",
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            if not config_loader:
                return {
                    "status": "error",
                    "error": "Server not initialized",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            return func(*args, **kwargs)  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Error in {func.__name__}", error=str(e), **kwargs)
            return {
                "status": "error",
                "error": f"Failed to execute {func.__name__}: {str(e)}",
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # Return appropriate wrapper based on whether function is async
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def validate_datasource(datasource_id: str) -> tuple[Any, str | None]:
    """Validate datasource exists and return it or error message."""
    if not config_loader:
        return None, "Server not initialized"
    datasource = config_loader.get_datasource(datasource_id)
    if not datasource:
        return None, f"Datasource not found: {datasource_id}"
    return datasource, None


# Discovery Tools


@app.tool()
@mcp_access_log("list_datasources")
@tool_error_handler
def list_datasources() -> dict[str, Any]:
    """List all available Prometheus datasources.

    Returns:
        Dict with list of configured Prometheus datasources
    """
    if not config_loader:
        return {
            "status": "error",
            "error": "Server not initialized",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    datasources = [
        {"id": name, "name": name, "url": ds.url, "type": "prometheus"}
        for name, ds in config_loader.datasources.items()
    ]
    return {
        "status": "success",
        "data": datasources,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.tool()
@mcp_access_log("list_metrics")
@tool_error_handler
async def list_metrics(datasource_id: str) -> dict[str, Any]:
    """Get all available metric names from a datasource.

    Args:
        datasource_id: ID of the Prometheus datasource

    Returns:
        Dict with list of metric names
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.get_metric_names()

    if result["status"] == "success":
        metrics = result["data"].get("data", [])
        return {
            "status": "success",
            "data": metrics,
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.tool()
@mcp_access_log("get_metric_metadata")
@tool_error_handler
async def get_metric_metadata(datasource_id: str, metric_name: str) -> dict[str, Any]:
    """Get metadata for a specific metric.

    Args:
        datasource_id: ID of the Prometheus datasource
        metric_name: Name of the metric to get metadata for

    Returns:
        Dict with metric metadata
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.get_metric_metadata(metric_name)

    if result["status"] == "success":
        return {
            "status": "success",
            "data": result["data"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Query Tools


@app.tool()
@mcp_access_log("query_instant")
@tool_error_handler
async def query_instant(
    datasource_id: str, promql: str, time: str | None = None
) -> dict[str, Any]:
    """Execute instant PromQL query.

    Args:
        datasource_id: ID of the Prometheus datasource
        promql: PromQL query string
        time: Optional timestamp (RFC3339 or Unix timestamp)

    Returns:
        Dict with query results

    Note:
        When using the time parameter, check your local system's current date/time
        to ensure queries use appropriate timestamps for meaningful results.
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.query_instant(promql, time)

    if result["status"] == "success":
        return {
            "status": "success",
            "data": result["data"],
            "datasource": datasource_id,
            "query": promql,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "query": promql,
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.tool()
@mcp_access_log("query_range")
@tool_error_handler
async def query_range(
    datasource_id: str, promql: str, start: str, end: str, step: str
) -> dict[str, Any]:
    """Execute range PromQL query.

    Args:
        datasource_id: ID of the Prometheus datasource
        promql: PromQL query string
        start: Start timestamp (RFC3339 or Unix timestamp)
        end: End timestamp (RFC3339 or Unix timestamp)
        step: Step duration (e.g., "30s", "1m", "5m")

    Returns:
        Dict with query results

    Note:
        Always check your local system's current date/time when constructing
        start and end timestamps to ensure queries cover the intended time range.
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.query_range(promql, start, end, step)

    if result["status"] == "success":
        return {
            "status": "success",
            "data": result["data"],
            "datasource": datasource_id,
            "query": promql,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "query": promql,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Analysis Helper Tools


@app.tool()
@mcp_access_log("get_metric_labels")
@tool_error_handler
async def get_metric_labels(datasource_id: str, metric_name: str) -> dict[str, Any]:
    """Get all label names for a specific metric.

    Args:
        datasource_id: ID of the Prometheus datasource
        metric_name: Name of the metric

    Returns:
        Dict with list of label names
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.get_series(f"{metric_name}")

    if result["status"] == "success":
        # Extract unique label names from series
        label_names = set()
        for series in result["data"].get("data", []):
            label_names.update(series.keys())
        # Remove __name__ as it's the metric name itself
        label_names.discard("__name__")

        return {
            "status": "success",
            "data": sorted(list(label_names)),
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.tool()
@mcp_access_log("get_label_values")
@tool_error_handler
async def get_label_values(
    datasource_id: str, label_name: str, metric_name: str | None = None
) -> dict[str, Any]:
    """Get all values for a specific label.

    Args:
        datasource_id: ID of the Prometheus datasource
        label_name: Name of the label
        metric_name: Optional metric name to filter by

    Returns:
        Dict with list of label values
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async with get_prometheus_client(datasource) as client:
        result = await client.get_label_values(label_name)

    if result["status"] == "success":
        values = result["data"].get("data", [])
        return {
            "status": "success",
            "data": values,
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


@app.tool()
@mcp_access_log("find_metrics_by_pattern")
@tool_error_handler
async def find_metrics_by_pattern(datasource_id: str, pattern: str) -> dict[str, Any]:
    """Find metrics matching a regex pattern.

    Args:
        datasource_id: ID of the Prometheus datasource
        pattern: Regex pattern to match against metric names

    Returns:
        Dict with list of matching metric names
    """
    datasource, error = validate_datasource(datasource_id)
    if error:
        return {
            "status": "error",
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # Get all metrics first
    async with get_prometheus_client(datasource) as client:
        result = await client.get_metric_names()

    if result["status"] != "success":
        return {
            "status": "error",
            "error": result["error"],
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # Filter by pattern
    all_metrics = result["data"].get("data", [])
    try:
        regex = re.compile(pattern)
        matching_metrics = [metric for metric in all_metrics if regex.search(metric)]
        return {
            "status": "success",
            "data": matching_metrics,
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except re.error as e:
        return {
            "status": "error",
            "error": f"Invalid regex pattern: {str(e)}",
            "datasource": datasource_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# MCP Tools Implementation


# Initialize the server on module load only if not in test environment
# Check for pytest or testing environment
if "pytest" not in sys.modules and not os.getenv("PYTEST_CURRENT_TEST"):
    initialize_server()


def main() -> None:
    """Main entry point for the server."""
    import os

    import uvicorn

    # Start health and metrics server (daemon thread will exit with main process)
    start_health_metrics_server(metrics_data)

    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    timeout_graceful_shutdown = int(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "8"))

    # Create the ASGI app from FastMCP
    asgi_app: Any = app.streamable_http_app()

    # Wrap with authentication middleware if active auth mode
    if auth_backend and get_auth_mode() == AuthMode.ACTIVE:
        # Import middleware here to avoid circular imports
        from .auth.middleware import AuthenticationMiddleware

        logger.info("Wrapping FastMCP ASGI app with authentication middleware")

        # Wrap the ASGI app with authentication middleware
        asgi_app = AuthenticationMiddleware(asgi_app, auth_backend=auth_backend)
        logger.info("Authentication middleware integrated successfully")
    else:
        logger.info("Running without authentication middleware (no-auth mode)")

    try:
        uvicorn.run(
            asgi_app,
            host=host,
            port=port,
            timeout_graceful_shutdown=timeout_graceful_shutdown,
            log_level="info",
            log_config=get_uvicorn_log_config(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()
