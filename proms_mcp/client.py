"""Prometheus API client wrapper with security validation."""

import os
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import httpx
import structlog

from .config import PrometheusDataSource

logger = structlog.get_logger()


class PrometheusClientError(Exception):
    """Base exception for Prometheus client errors."""

    pass


def prometheus_request_logger(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to log Prometheus API requests and responses."""

    @wraps(func)
    async def wrapper(
        self: "PrometheusClient", *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        # Generate correlation ID for request tracking
        correlation_id = f"prom-{int(time.time() * 1000)}-{id(args) % 10000}"
        method_name = func.__name__

        # Extract query info if available
        query = (
            args[0] if args and isinstance(args[0], str) else kwargs.get("query", "N/A")
        )
        query_preview = query[:100] + "..." if len(query) > 100 else query

        logger.info(
            f"Prometheus API call started: {method_name}",
            correlation_id=correlation_id,
            method=method_name,
            datasource=self.datasource.name,
            datasource_url=self.datasource.url,
            query_preview=query_preview if query != "N/A" else None,
            query_length=len(query) if query != "N/A" else 0,
            has_auth_header=bool(self.datasource.auth_header_value),
            timeout_seconds=self.timeout,
        )

        start_time = time.time()
        try:
            result = await func(self, *args, **kwargs)
            duration_ms = round((time.time() - start_time) * 1000, 2)

            # Log successful completion
            logger.info(
                f"Prometheus API call completed: {method_name}",
                correlation_id=correlation_id,
                method=method_name,
                datasource=self.datasource.name,
                duration_ms=duration_ms,
                status=result.get("status", "unknown"),
                has_data=bool(result.get("data")),
                result_size=len(str(result.get("data", ""))),
            )

            return result  # type: ignore[no-any-return]

        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(
                f"Prometheus API call failed: {method_name}",
                correlation_id=correlation_id,
                method=method_name,
                datasource=self.datasource.name,
                duration_ms=duration_ms,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    return wrapper


def prometheus_error_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to handle common Prometheus API errors."""

    @wraps(func)
    async def wrapper(
        self: "PrometheusClient", query: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        try:
            self._validate_promql(query)
            result = await func(self, query, *args, **kwargs)
            return result  # type: ignore[no-any-return]

        except PrometheusClientError as e:
            logger.warning("Query validation failed", query=query, error=str(e))
            return self._format_error(f"INVALID_QUERY: {str(e)}", query)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                error_msg = "AUTHENTICATION_FAILED: Invalid credentials"
            elif e.response.status_code == 400:
                error_msg = f"INVALID_QUERY: {e.response.text}"
            else:
                error_msg = f"PROMETHEUS_UNAVAILABLE: HTTP {e.response.status_code}"

            logger.error(
                "HTTP error", error=error_msg, status_code=e.response.status_code
            )
            return self._format_error(error_msg, query)

        except httpx.TimeoutException:
            error_msg = "TIMEOUT: Query timed out"
            logger.error("Query timeout", query=query, timeout=self.timeout)
            return self._format_error(error_msg, query)

        except Exception as e:
            error_msg = f"PROMETHEUS_UNAVAILABLE: {str(e)}"
            logger.error("Unexpected error", error=str(e))
            return self._format_error(error_msg, query)

    return wrapper


class PrometheusClient:
    """Prometheus API client wrapper with security and error handling."""

    def __init__(self, datasource: PrometheusDataSource, timeout: int = 30):
        self.datasource = datasource
        self.timeout = timeout

        # Setup headers
        headers = {}
        if datasource.auth_header_name and datasource.auth_header_value:
            headers[datasource.auth_header_name] = datasource.auth_header_value

        # Initialize httpx client for API calls
        self.http_client = httpx.AsyncClient(
            headers=headers, timeout=timeout, verify=True
        )

    async def __aenter__(self) -> "PrometheusClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.http_client.aclose()

    def _validate_promql(self, query: str) -> None:
        """Basic PromQL query validation."""
        if not query or not query.strip():
            raise PrometheusClientError("Query cannot be empty")

        if len(query) > 10000:
            raise PrometheusClientError("Query too long (max 10000 characters)")

    def _format_response(self, data: Any, query: str | None = None) -> dict[str, Any]:
        """Format response in standard format."""
        return {
            "status": "success",
            "datasource": self.datasource.name,
            "query": query,
            "data": data,
        }

    def _format_error(self, error: str, query: str | None = None) -> dict[str, Any]:
        """Format error response in standard format."""
        return {
            "status": "error",
            "datasource": self.datasource.name,
            "query": query,
            "error": error,
        }

    @prometheus_request_logger
    @prometheus_error_handler
    async def query_instant(
        self, query: str, time: str | None = None
    ) -> dict[str, Any]:
        """Execute instant PromQL query."""
        params = {"query": query}
        if time:
            params["time"] = time

        url = f"{self.datasource.url}/api/v1/query"

        # Log HTTP request details
        logger.info(
            "Prometheus HTTP request",
            method="GET",
            url=url,
            params_count=len(params),
            datasource=self.datasource.name,
            endpoint_type="query_instant",
        )

        import time as time_module

        request_start = time_module.time()
        response = await self.http_client.get(url, params=params)
        request_duration_ms = round((time_module.time() - request_start) * 1000, 2)

        logger.info(
            "Prometheus HTTP response",
            method="GET",
            status_code=response.status_code,
            response_size=len(response.content),
            duration_ms=request_duration_ms,
            datasource=self.datasource.name,
            endpoint_type="query_instant",
            content_type=response.headers.get("content-type", "unknown"),
        )

        response.raise_for_status()

        result = response.json()
        return self._format_response(result, query)

    @prometheus_request_logger
    @prometheus_error_handler
    async def query_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str,
    ) -> dict[str, Any]:
        """Execute range PromQL query."""
        params = {"query": query, "start": start, "end": end, "step": step}

        url = f"{self.datasource.url}/api/v1/query_range"

        logger.info(
            "Prometheus HTTP request",
            method="GET",
            url=url,
            params_count=len(params),
            datasource=self.datasource.name,
            endpoint_type="query_range",
            time_range=f"{start} to {end}",
            step=step,
        )

        import time as time_module

        request_start = time_module.time()
        response = await self.http_client.get(url, params=params)
        request_duration_ms = round((time_module.time() - request_start) * 1000, 2)

        logger.info(
            "Prometheus HTTP response",
            method="GET",
            status_code=response.status_code,
            response_size=len(response.content),
            duration_ms=request_duration_ms,
            datasource=self.datasource.name,
            endpoint_type="query_range",
            content_type=response.headers.get("content-type", "unknown"),
        )

        response.raise_for_status()

        result = response.json()
        return self._format_response(result, query)

    @prometheus_request_logger
    async def get_metric_names(self) -> dict[str, Any]:
        """Get all available metric names."""
        try:
            url = f"{self.datasource.url}/api/v1/label/__name__/values"

            logger.info(
                "Prometheus HTTP request",
                method="GET",
                url=url,
                datasource=self.datasource.name,
                endpoint_type="get_metric_names",
            )

            import time as time_module

            request_start = time_module.time()
            response = await self.http_client.get(url)
            request_duration_ms = round((time_module.time() - request_start) * 1000, 2)

            logger.info(
                "Prometheus HTTP response",
                method="GET",
                status_code=response.status_code,
                response_size=len(response.content)
                if hasattr(response.content, "__len__")
                else 0,
                duration_ms=request_duration_ms,
                datasource=self.datasource.name,
                endpoint_type="get_metric_names",
                content_type=response.headers.get("content-type", "unknown"),
            )

            response.raise_for_status()

            result = response.json()
            return self._format_response(result)

        except Exception as e:
            error_msg = f"PROMETHEUS_UNAVAILABLE: {str(e)}"
            logger.error("Error getting metric names", error=str(e))
            return self._format_error(error_msg)

    @prometheus_request_logger
    async def get_metric_metadata(self, metric_name: str) -> dict[str, Any]:
        """Get metadata for a specific metric."""
        try:
            url = f"{self.datasource.url}/api/v1/metadata"
            params = {"metric": metric_name}
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()

            result = response.json()
            return self._format_response(result)

        except Exception as e:
            error_msg = f"PROMETHEUS_UNAVAILABLE: {str(e)}"
            logger.error(
                "Error getting metric metadata", metric=metric_name, error=str(e)
            )
            return self._format_error(error_msg)

    @prometheus_request_logger
    async def get_series(self, match: str) -> dict[str, Any]:
        """Get series matching the given selector."""
        try:
            url = f"{self.datasource.url}/api/v1/series"
            params = {"match[]": match}
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()

            result = response.json()
            return self._format_response(result)

        except Exception as e:
            error_msg = f"PROMETHEUS_UNAVAILABLE: {str(e)}"
            logger.error("Error getting series", match=match, error=str(e))
            return self._format_error(error_msg)

    @prometheus_request_logger
    async def get_label_values(self, label_name: str) -> dict[str, Any]:
        """Get all values for a specific label."""
        try:
            url = f"{self.datasource.url}/api/v1/label/{label_name}/values"
            response = await self.http_client.get(url)
            response.raise_for_status()

            result = response.json()
            return self._format_response(result)

        except Exception as e:
            error_msg = f"PROMETHEUS_UNAVAILABLE: {str(e)}"
            logger.error("Error getting label values", label=label_name, error=str(e))
            return self._format_error(error_msg)


def get_prometheus_client(datasource: PrometheusDataSource) -> PrometheusClient:
    """Get configured Prometheus client for a datasource."""
    timeout = int(os.getenv("QUERY_TIMEOUT", "30"))
    return PrometheusClient(datasource, timeout)
