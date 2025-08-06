"""Unit tests for client module."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from proms_mcp.client import (
    PrometheusClient,
    PrometheusClientError,
    get_prometheus_client,
)
from proms_mcp.config import PrometheusDataSource


class TestPrometheusClient:
    """Test PrometheusClient class."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.datasource = PrometheusDataSource(
            name="test-prometheus",
            url="https://prometheus.example.com",
            auth_header_name="Authorization",
            auth_header_value="Bearer test-token",
        )
        self.client = PrometheusClient(self.datasource, timeout=30)

    def test_initialization(self) -> None:
        """Test client initialization."""
        assert self.client.datasource == self.datasource
        assert self.client.timeout == 30
        assert self.client.datasource == self.datasource

    def test_initialization_without_auth(self) -> None:
        """Test client initialization without auth headers."""
        datasource = PrometheusDataSource(
            name="test-prometheus",
            url="https://prometheus.example.com",
        )
        client = PrometheusClient(datasource)
        assert client.datasource == datasource

    def test_validate_promql_valid_queries(self) -> None:
        """Test validation of valid PromQL queries."""
        valid_queries = [
            "up",
            "rate(http_requests_total[5m])",
            "sum(rate(cpu_usage[1h]))",
            "histogram_quantile(0.95, rate(http_duration_bucket[5d]))",
        ]

        for query in valid_queries:
            # Should not raise exception
            self.client._validate_promql(query)

    def test_validate_promql_basic_queries(self) -> None:
        """Test basic validation passes valid queries."""
        valid_queries = [
            "rate(metric[1y])",  # Year range
            "rate(metric[1w])",  # Week range
            '{job=~".*"*}',  # Complex regex
            "metric[9999s]",  # Large time range
        ]

        for query in valid_queries:
            # Basic validation should pass these queries
            self.client._validate_promql(query)

    def test_validate_promql_empty_query(self) -> None:
        """Test validation of empty queries."""
        with pytest.raises(PrometheusClientError, match="Query cannot be empty"):
            self.client._validate_promql("")

        with pytest.raises(PrometheusClientError, match="Query cannot be empty"):
            self.client._validate_promql("   ")

    def test_validate_promql_too_long(self) -> None:
        """Test validation of overly long queries."""
        long_query = "up" * 5001  # > 10000 characters (10002 chars)
        with pytest.raises(PrometheusClientError, match="Query too long"):
            self.client._validate_promql(long_query)

    def test_format_response(self) -> None:
        """Test response formatting."""
        data = {"status": "success", "data": {"result": []}}
        query = "up"

        response = self.client._format_response(data, query)

        assert response["status"] == "success"
        assert response["datasource"] == "test-prometheus"
        assert response["query"] == query
        assert response["data"] == data
        # Timestamp and correlation_id removed from response format

    def test_format_error(self) -> None:
        """Test error formatting."""
        error = "Test error message"
        query = "up"

        response = self.client._format_error(error, query)

        assert response["status"] == "error"
        assert response["datasource"] == "test-prometheus"
        assert response["query"] == query
        assert response["error"] == error
        # Timestamp and correlation_id removed from response format

    @pytest.mark.asyncio
    async def test_query_instant_success(self) -> None:
        """Test successful instant query."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "success", "data": {"result": []}}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "success", "data": {"result": []}}

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.query_instant("up")

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            assert result["query"] == "up"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_instant_with_mock_response(self) -> None:
        """Test instant query with mocked successful response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "success", "data": {"result": []}}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "success", "data": {"result": []}}

        with patch.object(self.client.http_client, "get", return_value=mock_response):
            result = await self.client.query_instant("up")

        assert result["status"] == "success"
        assert result["datasource"] == "test-prometheus"

    @pytest.mark.asyncio
    async def test_query_instant_http_error(self) -> None:
        """Test instant query with HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.HTTPStatusError(
                "Bad Request", request=Mock(), response=mock_response
            )

            result = await self.client.query_instant("up")

            assert result["status"] == "error"
            assert "INVALID_QUERY" in result["error"]

    @pytest.mark.asyncio
    async def test_query_instant_auth_error(self) -> None:
        """Test instant query with authentication error."""
        mock_response = Mock()
        mock_response.status_code = 401

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=Mock(), response=mock_response
            )

            result = await self.client.query_instant("up")

            assert result["status"] == "error"
            assert "AUTHENTICATION_FAILED" in result["error"]

    @pytest.mark.asyncio
    async def test_query_instant_timeout(self) -> None:
        """Test instant query with timeout."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Timeout")

            result = await self.client.query_instant("up")

            assert result["status"] == "error"
            assert "TIMEOUT" in result["error"]

    @pytest.mark.asyncio
    async def test_query_range_success(self) -> None:
        """Test successful range query."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "success", "data": {"result": []}}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "success", "data": {"result": []}}

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.query_range(
                "up", "2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", "30s"
            )

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            assert result["query"] == "up"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_metric_names_success(self) -> None:
        """Test successful metric names retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "success", "data": ["up", "cpu_usage", "memory_usage"]}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "status": "success",
            "data": ["up", "cpu_usage", "memory_usage"],
        }

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.get_metric_names()

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_metric_metadata_success(self) -> None:
        """Test successful metric metadata retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "up": [
                    {
                        "type": "gauge",
                        "help": "1 if the instance is healthy",
                        "unit": "",
                    }
                ]
            },
        }

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.get_metric_metadata("up")

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_series_success(self) -> None:
        """Test successful series retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": "success",
            "data": [
                {"__name__": "up", "job": "prometheus", "instance": "localhost:9090"}
            ],
        }

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.get_series("{up}")

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_label_values_success(self) -> None:
        """Test successful label values retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": "success",
            "data": ["prometheus", "node-exporter", "alertmanager"],
        }

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.get_label_values("job")

            assert result["status"] == "success"
            assert result["datasource"] == "test-prometheus"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager usage."""
        async with self.client as client:
            assert client == self.client

        # Verify http_client.aclose was called
        # Note: In real usage, this would close the HTTP client

    # NEW TESTS FOR MISSING COVERAGE

    @pytest.mark.asyncio
    async def test_get_metric_names_error(self) -> None:
        """Test get_metric_names with error."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Connection error")

            result = await self.client.get_metric_names()

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_get_metric_metadata_error(self) -> None:
        """Test get_metric_metadata with error."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Connection error")

            result = await self.client.get_metric_metadata("up")

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_get_series_error(self) -> None:
        """Test get_series with error."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Connection error")

            result = await self.client.get_series("{up}")

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_get_label_values_error(self) -> None:
        """Test get_label_values with error."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Connection error")

            result = await self.client.get_label_values("job")

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_query_instant_with_time_parameter(self) -> None:
        """Test instant query with time parameter."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "success", "data": {"result": []}}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"status": "success", "data": {"result": []}}

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            result = await self.client.query_instant("up", time="2024-01-01T00:00:00Z")

            assert result["status"] == "success"
            mock_get.assert_called_once()
            # Verify the time parameter was passed
            call_args = mock_get.call_args
            assert call_args[1]["params"]["time"] == "2024-01-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_query_instant_general_http_error(self) -> None:
        """Test instant query with general HTTP error (not 400 or 401)."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.HTTPStatusError(
                "Internal Server Error", request=Mock(), response=mock_response
            )

            result = await self.client.query_instant("up")

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "HTTP 500" in result["error"]

    @pytest.mark.asyncio
    async def test_query_instant_general_exception(self) -> None:
        """Test instant query with general exception."""
        with patch.object(
            self.client.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Network error")

            result = await self.client.query_instant("up")

            assert result["status"] == "error"
            assert "PROMETHEUS_UNAVAILABLE" in result["error"]
            assert "Network error" in result["error"]

    @pytest.mark.asyncio
    async def test_query_range_validation_error(self) -> None:
        """Test range query with validation error."""
        result = await self.client.query_range("", "start", "end", "step")

        assert result["status"] == "error"
        assert "INVALID_QUERY" in result["error"]
        assert "Query cannot be empty" in result["error"]

    def test_format_response_without_query(self) -> None:
        """Test response formatting without query parameter."""
        data = {"status": "success", "data": {"result": []}}

        response = self.client._format_response(data)

        assert response["status"] == "success"
        assert response["datasource"] == "test-prometheus"
        assert response["query"] is None
        assert response["data"] == data

    def test_format_error_without_query(self) -> None:
        """Test error formatting without query parameter."""
        error = "Test error message"

        response = self.client._format_error(error)

        assert response["status"] == "error"
        assert response["datasource"] == "test-prometheus"
        assert response["query"] is None
        assert response["error"] == error


def test_get_prometheus_client() -> None:
    """Test get_prometheus_client factory function."""
    datasource = PrometheusDataSource(
        name="test-prometheus", url="https://prometheus.example.com"
    )

    with patch.dict("os.environ", {"QUERY_TIMEOUT": "60"}):
        client = get_prometheus_client(datasource)
        assert client.datasource == datasource
        assert client.timeout == 60

    # Test default timeout
    with patch.dict("os.environ", {}, clear=True):
        client = get_prometheus_client(datasource)
        assert client.timeout == 30
