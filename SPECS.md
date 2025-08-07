# Proms MCP Server Specification

## Overview

A lean MCP (Model Context Protocol) server that provides LLM agents with transparent access to multiple Prometheus instances for metrics analysis and SRE operations.

## Core Requirements

### Deployment Environment

- **Platform**: OpenShift cluster (Kubernetes pod)
- **Language**: Python 3.11+ (using Red Hat UBI9 Python base image)
- **Architecture**: Single container, stateless
- **Configuration**: Grafana datasource YAML files mounted as ConfigMap
- **Network**: HTTP access (SSL termination handled externally)

### Design Principles

- **VERY LEAN**: No over-engineering, minimal dependencies
- **Stateless**: No database, no persistent storage
- **Direct passthrough**: Minimal data transformation
- **Fail fast**: Simple error handling, let MCP handle protocol errors

## Technical Stack

### Python Project Management

- **Tool**: `uv` for dependency management and virtual environments
- **Linting/Formatting**: `uv run ruff check` and `uv run ruff format`
- **Project file**: `pyproject.toml` with uv configuration

### Required Dependencies

**Production dependencies:**

- `fastmcp>=2.11.0` - Modern MCP library with built-in HTTP transport and authentication
- `pyyaml>=6.0.2` - YAML configuration parsing
- `httpx>=0.28.0` - HTTP client for Prometheus API calls and OpenShift user info authentication
- `structlog>=24.4.0` - Structured logging
- `pydantic>=2.11.0` - Data validation and serialization

**Development dependencies:**

- `pytest>=7.0.0` with `pytest-asyncio>=0.21.0` and `pytest-cov>=4.0.0` for testing
- `ruff>=0.1.0` for linting and formatting
- `mypy>=1.8.0` with `types-PyYAML>=6.0.0` for type checking

### File Structure

```none
/app/
  proms_mcp/
    server.py            # FastMCP server with @tool decorators and auth integration
    client.py            # Prometheus API wrapper
    config.py            # Grafana YAML config parser with auth mode support
    auth.py              # OpenShift user info based authentication for FastMCP
    monitoring.py        # Health and metrics HTTP endpoints
    logging.py           # Structured logging configuration
  pyproject.toml         # uv project configuration
  Dockerfile             # Container definition
  README.md              # Usage instructions + local development
  Makefile               # Development commands
  /openshift/
    deploy.yaml          # OpenShift Template with RBAC support
  /tests/
    test_*.py            # Unit and integration tests
```

## Configuration Management

### Grafana Datasource Integration

- **Source**: OpenShift Secret containing Grafana datasource provisioning YAML file
- **Mount point**: `/etc/grafana/provisioning/datasources/datasources.yaml` (from OpenShift Secret)
- **Format**: Standard Grafana datasource YAML as per <https://grafana.com/docs/grafana/latest/administration/provisioning/#data-sources>
- **Loading**: Parse single YAML file on startup
- **Filtering**: Only process datasources with `"type": "prometheus"` - skip all other types
- **Reload**: Static configuration (no runtime reload needed for v1)

### Expected Datasource YAML Structure

- **Format**: Standard Grafana datasource YAML format
- **API version**: Must be `apiVersion: 1`
- **Datasource filtering**: Only process entries where `type: "prometheus"`
- **Required fields per datasource**: `name`, `url`, `type`, `jsonData.httpHeaderName1`, `secureJsonData.httpHeaderValue1`
- **Authentication**: Bearer token via `jsonData.httpHeaderName1` and `secureJsonData.httpHeaderValue1`
- **Mixed datasources**: Non-prometheus datasources (e.g., Loki) will be ignored

### Required Datasource Fields (for type="prometheus" only)

Extract and validate these fields from each prometheus datasource:

- `name`: Datasource identifier (used as datasource_id in MCP tools)
- `url`: Prometheus instance URL
- `type`: Must equal "prometheus" (filter condition)
- `jsonData.httpHeaderName1`: Bearer token header name (typically "Authorization")
- `secureJsonData.httpHeaderValue1`: Bearer token value (e.g., "Bearer MYTOKEN")

## MCP Tools Specification

### Tool Categories

#### 1. Discovery Tools

- **list_datasources()**: Returns list of all configured Prometheus datasources with id, url, type
- **list_metrics(datasource_id)**: Get all metric names using `/api/v1/label/__name__/values`
- **get_metric_metadata(datasource_id, metric_name)**: Get metric metadata using `/api/v1/metadata`

#### 2. Query Tools

- **query_instant(datasource_id, promql, time?)**: Execute instant PromQL query using `/api/v1/query`
- **query_range(datasource_id, promql, start, end, step)**: Execute range PromQL query using `/api/v1/query_range`

#### 3. Analysis Helper Tools

- **get_metric_labels(datasource_id, metric_name)**: Get all label names for a metric using `/api/v1/series`
- **get_label_values(datasource_id, label_name, metric_name?)**: Get all values for a label using `/api/v1/label/{label_name}/values`
- **find_metrics_by_pattern(datasource_id, pattern)**: Find metrics matching regex pattern via client-side filtering

## Data Format Standards

### Tool Response Format

All tools must return structured JSON with consistent formatting:

- **status**: "success" or "error"
- **timestamp**: ISO 8601 UTC timestamp
- **datasource**: datasource_id (for datasource-specific tools)
- **query**: original PromQL query (for query tools)
- **data**: Prometheus API response data unchanged
- **error**: error message (only if status == "error")

### Time Series Data Preservation

- **No aggregation**: Pass through Prometheus data unchanged
- **Timestamps**: Preserve Unix timestamps as returned by Prometheus
- **Labels**: Maintain all metric labels and their values
- **Values**: Keep numeric precision as returned by API

## Error Handling

### Validation Rules

1. **Datasource ID**: Must exist in loaded configuration
2. **PromQL**: Basic syntax validation (non-empty, reasonable length)
3. **Time parameters**: Must be valid RFC3339 or Unix timestamps
4. **Step parameter**: Must be valid duration string

### Error Response Format

- **status**: Must be "error"
- **error**: Clear error message
- **datasource**: datasource_id (if applicable)
- **details**: Additional context (if helpful)

### Error Categories

- `DATASOURCE_NOT_FOUND`: Invalid datasource_id
- `PROMETHEUS_UNAVAILABLE`: Network/connection issues
- `INVALID_QUERY`: PromQL syntax errors
- `AUTHENTICATION_FAILED`: Credential issues
- `TIMEOUT`: Query timeout (set to 30s default)

## FastMCP Server Implementation

### MCP Protocol Handling

- **Transport**: FastMCP streamable HTTP transport (stateless mode)
- **Protocol**: Standard MCP JSON-RPC 2.0 (handled automatically)
- **Server**: Uvicorn ASGI server
- **Port**: 8000 (configurable via PORT env var)
- **Session Management**: Stateless HTTP mode prevents reconnection issues after server restarts
- **Tools**: Registered using `@app.tool()` decorators

### Health and Metrics Endpoints

- **Health Endpoint**: `GET /health` on port 8080 (configurable via HEALTH_METRICS_PORT)
- **Metrics Endpoint**: `GET /metrics` on port 8080 (Prometheus format)
- **Implementation**: Dedicated `monitoring.py` module with HTTP server in background thread
- **Health Response**: JSON with status, uptime, datasource count, connected clients
- **Metrics Format**: Standard Prometheus metrics format with histograms and counters
- **Modular Design**: Separated from main MCP server for clean architecture

### Shutdown Handling

The server uses streamable HTTP transport with enhanced shutdown handling to deal with persistent MCP connections:

- **Built-in Timeout**: Uses uvicorn's native `--timeout-graceful-shutdown` parameter for reliable shutdown
- **Graceful Shutdown**: Uvicorn attempts to close connections gracefully first
- **Forced Shutdown**: After the timeout (default: 8 seconds), uvicorn forcefully closes remaining connections
- **Container Integration**: The timeout is set to work with OpenShift's `terminationGracePeriodSeconds: 10` setting

- **Native Implementation**: Uses uvicorn's built-in shutdown handling instead of custom workarounds

This ensures reliable shutdown behavior even with persistent client connections (like Cursor) that may not close immediately, using uvicorn's proven shutdown mechanisms.

### Server Architecture

- **Single File**: All tools in `server.py` using decorators
- **ASGI App**: The `app` object in `server.py` is the core ASGI application.
- **No Manual Routing**: Tools automatically registered and routed
- **Structured Responses**: All tools return JSON strings with consistent format

## Container Specification

### Dockerfile Requirements

- **Multi-stage build**: Must include base, builder, test, and production stages
- **Base image**: Red Hat UBI9 Python 3.11+ with specific version tag and SHA digest (no `latest` tags)
- **Base registry**: Use `registry.redhat.io` for official Red Hat images
- **Dependency management**: Use `uv` for Python package management
- **Test integration**: Test stage must run full test suite - build fails if tests fail
- **Production optimization**: Final stage contains only runtime dependencies
- **Port exposure**: Expose ports 8000 (MCP) and 8080 (health/metrics)
- **Entry point**: Use `uv run python -m proms_mcp` as CMD

### Multi-Stage Build Requirements

- **Base Image**: Must use Red Hat UBI9 Python with specific version tag and SHA digest (no `latest` tags)
- **Test Stage**: Must run full test suite as part of build process - build fails if tests fail
- **Production Stage**: Lean final image with only runtime dependencies
- **Security**: Uses official Red Hat registry images for enterprise compliance
- **Build Targets**:
  - `docker build --target test` - Build and run tests only
  - `docker build --target prod` - Build production image (default)
  - `docker build .` - Full build including test execution

### Environment Variables

- `PORT`: MCP server port (default: 8000)
- `HEALTH_METRICS_PORT`: Health and metrics server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)
- `GRAFANA_DATASOURCES_PATH`: Path to datasource config file (default: /etc/grafana/provisioning/datasources/datasources.yaml)
- `QUERY_TIMEOUT`: Query timeout in seconds (default: 30)
- `AUTH_MODE`: Authentication mode (`none` or `active`, default: `active`)
- `AUTH_CACHE_TTL_SECONDS`: Authentication cache TTL in seconds (default: 300 = 5 minutes)
- `OPENSHIFT_API_URL`: OpenShift API server URL for user info authentication
- `OPENSHIFT_CA_CERT_PATH`: Optional CA certificate path for custom TLS verification

### Resource Limits

- **Memory**: Configurable request/limit (default: 256Mi request, 512Mi limit)
- **CPU**: Configurable request only, no limit (default: 100m request)
- **Template Variables**: `MEMORY_REQUEST`, `MEMORY_LIMIT`, `CPU_REQUEST`

## Performance Requirements

### Response Times

- Discovery tools: < 5 seconds
- Instant queries: < 10 seconds  
- Range queries: < 30 seconds
- Startup time: < 10 seconds

### Concurrency

- Handle up to 10 concurrent MCP requests
- Connection pooling for Prometheus APIs
- Graceful handling of slow queries

## Security Considerations

### Authentication

- **MCP Endpoint**: OpenShift user info based bearer token authentication using OpenShift tokens
- **Authentication Provider**: Custom `OpenShiftUserVerifier` implementing FastMCP's `TokenVerifier` interface
- **Token Validation**: Uses OpenShift user info API (`/apis/user.openshift.io/v1/users/~`) - accessible to all authenticated users
- **No Special Permissions**: Works with any valid service account token, no `system:auth-delegator` required
- **TLS Security**: Automatic CA certificate detection (in-cluster or system CA store)
- **Prometheus Connections**: Bearer token authentication using credentials from Grafana datasource config
- Authentication via `jsonData.httpHeaderName1` and `secureJsonData.httpHeaderValue1` fields
- **Security**: No credential storage beyond runtime memory, comprehensive audit logging

### Network Security

- Input sanitization for PromQL queries
- Validate Prometheus URLs from datasource config against expected patterns

### PromQL Query Validation

Basic security checks are implemented:

- Query length validation (max 10,000 characters)
- Empty query validation
- Basic input sanitization via httpx parameter encoding

Note: Advanced security patterns were removed to keep the implementation lean. Hours (`h`) and days (`d`) ranges are allowed for legitimate analysis.

## Modern MCP Library Benefits

**FastMCP Implementation Requirements:**

- **Library**: Use FastMCP library v2.11.0+ with built-in HTTP transport and authentication
- **Decorator pattern**: Implement all tools using `@app.tool()` decorators
- **Authentication**: Integrate custom `OpenShiftUserVerifier` with FastMCP's auth system
- **Server initialization**: Create FastMCP app instance with auth provider
- **Tool registration**: Automatic tool registration and routing via decorators
- **Type hints**: Use proper Python type hints for all tool parameters and return types
- **Documentation**: Include docstrings for all tools for automatic MCP tool descriptions

## Implementation Guidelines

### Code Style

- **Functions**: Max 50 lines, single responsibility
- **Error handling**: Use exceptions, not error codes
- **Logging**: Structured logging with correlation IDs using `structlog`
- **Comments**: Minimal, code should be self-documenting

### Observability Implementation

**Structured Logging Requirements:**

- **JSON format**: All logs in structured JSON for parsing
- **Access logging**: Track all MCP tool calls with timing and status
- **Error tracking**: Detailed error logging with error types and context
- **INFO level default**: All loggers (FastMCP, MCP, Uvicorn) use INFO level for visibility

**Required log fields:**

- `level`: INFO, ERROR, WARNING
- `tool`: MCP tool name (for access logs)
- `datasource`: Datasource ID when applicable
- `duration_ms`: Request duration in milliseconds
- `status`: success/error for tool calls
- `request_id`: Simple correlation ID (based on args hash)

**Prometheus Metrics Collected:**

- `proms_mcp_tool_requests_total`: Counter by tool name and status
- `proms_mcp_tool_request_duration_seconds`: Histogram by tool name with buckets
- `proms_mcp_server_requests_total`: Counter by HTTP method and endpoint
- `proms_mcp_datasources_configured`: Gauge of configured datasources
- `proms_mcp_connected_clients`: Gauge of active client connections (basic tracking)

**Implementation Requirements:**

- **Logging libraries**: Use `structlog` for structured logging with INFO level default
- **Access logging decorator**: Implement decorator for all MCP tools to track timing and status
- **Logger configuration**: Set INFO level for FastMCP, MCP, and Uvicorn loggers
- **Metrics collection**: Use Prometheus client library for metrics endpoints
- **Decorator pattern**: Apply logging and error handling decorators to all `@app.tool()` functions

### Testing Strategy

- **Coverage**: >95% unit and integration test coverage
- **Tools**: pytest with coverage reporting (`uv run pytest --cov`)
- Unit tests for config parsing and all MCP tools
- Integration tests with mock Prometheus API responses
- Health check and metrics endpoint validation
- Error handling and edge case coverage
- Basic load testing for concurrent requests

### Development Approach

1. Implement config_loader.py first
2. Build prometheus_client.py wrapper
3. Create MCP tools one category at a time
4. Add HTTP server wrapper
5. Create Dockerfile and test deployment

## Success Criteria

The implementation is complete when:

1. All specified MCP tools are functional
2. Multiple Prometheus instances can be queried transparently  
3. LLM can perform comprehensive metrics analysis using only these tools
4. Server runs stably in OpenShift pod with provided template
5. Response times meet performance requirements
6. All error conditions are handled gracefully
7. **Test coverage >95% with all tests passing**
8. Metrics collection for tool usage and performance
9. Local development setup documented and working

## Future Considerations (Out of Scope for V1)

- Configuration hot-reload
- Query result caching  
- Advanced authentication methods
- Custom dashboarding endpoints
- Circuit breaker pattern for failing Prometheus instances
- Retry logic with exponential backoff for failed requests
- Rate limiting to prevent overwhelming Prometheus instances
- Datasource health monitoring and automatic failover

## OpenShift Deployment Template

### Template Location

`/openshift/deploy.yaml` - OpenShift Template with the following parameters:

**Required Parameters:**

- `IMAGE`: Container image name
- `IMAGE_TAG`: Git commit SHA (7 characters)

**Optional Parameters (with defaults):**

- `MEMORY_REQUEST`: "256Mi"
- `MEMORY_LIMIT`: "512Mi"
- `CPU_REQUEST`: "100m"

**Template Components:**

- **ServiceAccount**: `proms-mcp-server` for pod identity (no special permissions needed)
- **Deployment**: Configurable resources with authentication environment variables
- **Service**: Exposes ports 8000 (MCP) and 8080 (health/metrics)
- **Route**: TLS-enabled external access with cert-manager integration
- **PodDisruptionBudget**: Ensures high availability
- **Secret mount**: Datasource configuration at `/etc/grafana/provisioning/datasources/`

**Prerequisites (not included in template):**

- **Secret requirement**: OpenShift Secret containing Grafana datasource YAML files
- **Secret name**: Must be referenced in template for volume mounting (default: `grafana-datasources`)
- **Secret type**: Opaque with `stringData.datasources.yaml` key
- **Content format**: Standard Grafana datasource YAML with prometheus and other datasources
- **Mixed datasources**: Can include non-prometheus datasources (will be filtered out)
- **Authentication**: Must include Bearer tokens in `secureJsonData.httpHeaderValue1`

## README.md Requirements

### Local Development Section

Must include detailed instructions for:

**Container Development:**

- **Multi-stage build**: Support `podman build --target test` for test-only builds
- **Production build**: Support `podman build --target prod` for production images
- **Full build**: Default `podman build .` runs tests and creates production image
- **Configuration**: Mount datasource YAML at `/etc/grafana/provisioning/datasources/datasources.yaml`
- **Port mapping**: Expose ports 8000 (MCP) and 8080 (health/metrics)
- **Sample config**: Provide example datasource YAML for local development
- **Transport**: Uses FastMCP streamable HTTP transport for MCP protocol

**Development Environment:**

- **Setup**: Use `uv sync` for dependency installation
- **Makefile support**: Provide `make lint`, `make test`, `make run` commands
- **Direct execution**: Support `uv run python -m proms_mcp` for module execution
- **Testing**: Use `uv run pytest --cov --cov-report=html` for coverage reports
- **Linting**: Use `uv run ruff check --fix` for code formatting and linting
- **Environment**: Set `PYTHONPATH=.` for proper module resolution in development
