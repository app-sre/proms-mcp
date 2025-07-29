# Promesh MCP Server Specification

## Overview
A lean MCP (Model Context Protocol) server that provides LLM agents with transparent access to multiple Prometheus instances for metrics analysis and SRE operations.

## Core Requirements

### Deployment Environment
- **Platform**: OpenShift cluster (Kubernetes pod)
- **Language**: Python 3.11+
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
```toml
[project]
dependencies = [
    "mcp>=1.12.0",
    "fastmcp-http>=0.1.4",
    "pyyaml>=6.0",
    "httpx>=0.24.0",
    "structlog>=23.0.0",
    "pydantic>=2.0.0"
]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
    "types-PyYAML>=6.0.0"
]

# Note: FastMCP with streamable HTTP transport for production deployment
# Use: uv run python -m promesh_mcp, uv run pytest --cov --cov-report=html, etc.
# Development: make run (uses proper module execution)
```

### File Structure
```
/app/
  server.py              # FastMCP server with @tool decorators
  client.py              # Prometheus API wrapper
  config.py              # Grafana YAML config parser
  monitoring.py          # Health and metrics HTTP endpoints
  pyproject.toml        # uv project configuration
  Dockerfile            # Container definition
  README.md             # Usage instructions + local development
  Makefile              # Development commands
  /openshift/
    deploy.yaml         # OpenShift Template for deployment
  /tests/
    test_*.py           # Unit and integration tests
```

## Configuration Management

### Grafana Datasource Integration
- **Source**: OpenShift Secret containing Grafana datasource provisioning YAML file
- **Mount point**: `/etc/grafana/provisioning/datasources/datasources.yaml` (from OpenShift Secret)
- **Format**: Standard Grafana datasource YAML as per https://grafana.com/docs/grafana/latest/administration/provisioning/#data-sources
- **Loading**: Parse single YAML file on startup
- **Filtering**: Only process datasources with `"type": "prometheus"` - skip all other types
- **Reload**: Static configuration (no runtime reload needed for v1)

### Expected Datasource YAML Structure
```yaml
apiVersion: 1
prune: true
datasources:
  - access: "proxy"
    editable: false
    jsonData:
      httpHeaderName1: "Authorization"
    name: "cluster-name-prometheus"
    orgId: 1  
    secureJsonData:
      httpHeaderValue1: "Bearer <token>"
    type: "prometheus"
    url: "https://prometheus.example.com"
    version: 1
  - type: "loki"  # This will be skipped
    name: "loki-datasource"
    # ... other fields
```

### Required Datasource Fields (for type="prometheus" only)
Extract and validate these fields from each prometheus datasource:
- `name`: Datasource identifier (used as datasource_id in MCP tools)
- `url`: Prometheus instance URL
- `type`: Must equal "prometheus" (filter condition)
- `jsonData.httpHeaderName1`: Bearer token header name (typically "Authorization")
- `secureJsonData.httpHeaderValue1`: Bearer token value (e.g., "Bearer <token>")

## MCP Tools Specification

### Tool Categories

#### 1. Discovery Tools
```python
@tool
def list_datasources() -> list[dict]:
    """List all available Prometheus datasources"""
    # Returns: [{"id": "datasource_name", "url": "...", "type": "prometheus"}]

@tool  
def list_metrics(datasource_id: str) -> list[str]:
    """Get all available metric names from a datasource"""
    # Uses: GET /api/v1/label/__name__/values

@tool
def get_metric_metadata(datasource_id: str, metric_name: str) -> dict:
    """Get metadata for a specific metric"""
    # Uses: GET /api/v1/metadata
    # Returns: type, help, unit information
```

#### 2. Query Tools
```python
@tool
def query_instant(datasource_id: str, promql: str, time: str = None) -> dict:
    """Execute instant PromQL query"""
    # Uses: GET /api/v1/query
    # time format: RFC3339 or Unix timestamp

@tool
def query_range(datasource_id: str, promql: str, start: str, end: str, step: str) -> dict:
    """Execute range PromQL query"""
    # Uses: GET /api/v1/query_range
    # step format: duration string (e.g., "30s", "1m", "5m")

@tool
def query_prometheus(datasource_id: str, promql: str, start_time: str = None, end_time: str = None) -> dict:
    """Smart query that chooses instant or range based on parameters"""
    # Wrapper that calls query_instant or query_range based on parameters
```

#### 3. Analysis Helper Tools
```python
@tool
def get_metric_labels(datasource_id: str, metric_name: str) -> list[str]:
    """Get all label names for a specific metric"""
    # Uses: GET /api/v1/series?match[]={metric_name}

@tool
def get_label_values(datasource_id: str, label_name: str, metric_name: str = None) -> list[str]:
    """Get all values for a specific label"""
    # Uses: GET /api/v1/label/{label_name}/values

@tool
def find_metrics_by_pattern(datasource_id: str, pattern: str) -> list[str]:
    """Find metrics matching a regex pattern"""
    # Client-side filtering of list_metrics() results
```

## Data Format Standards

### Tool Response Format
All tools must return structured data with consistent formatting:

```python
{
    "status": "success" | "error",
    "timestamp": "2025-07-25T12:00:00+00:00",  # ISO 8601 UTC timestamp
    "datasource": "datasource_id",  # for datasource-specific tools
    "query": "original_promql_query",  # for query tools
    "data": {
        # Prometheus API response data unchanged
    },
    "error": "error_message"  # only if status == "error"
}
```

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
```python
{
    "status": "error",
    "error": "Clear error message",
    "datasource": "datasource_id",  # if applicable
    "details": {}  # Additional context if helpful
}
```

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
- **Configurable**: Use `SHUTDOWN_TIMEOUT_SECONDS` environment variable to adjust the timeout
- **Native Implementation**: Uses uvicorn's built-in shutdown handling instead of custom workarounds

This ensures reliable shutdown behavior even with persistent client connections (like Cursor) that may not close immediately, using uvicorn's proven shutdown mechanisms.

### Server Architecture
- **Single File**: All tools in `server.py` using decorators
- **ASGI App**: The `app` object in `server.py` is the core ASGI application.
- **No Manual Routing**: Tools automatically registered and routed
- **Structured Responses**: All tools return JSON strings with consistent format

## Container Specification

### Dockerfile Requirements
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --frozen
COPY . .
EXPOSE 8000
CMD ["uv", "run", "python", "-m", "promesh_mcp"]
```

### Environment Variables
- `PORT`: MCP server port (default: 8000)
- `HEALTH_METRICS_PORT`: Health and metrics server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)
- `GRAFANA_DATASOURCES_PATH`: Path to datasource config file (default: /etc/grafana/provisioning/datasources/datasources.yaml)
- `QUERY_TIMEOUT`: Query timeout in seconds (default: 30)
- `SHUTDOWN_TIMEOUT_SECONDS`: Forced shutdown timeout in seconds (default: 8)

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
- **MCP Endpoint**: Unauthenticated (internal cluster access)
- **Prometheus Connections**: Bearer token authentication only using credentials from Grafana datasource config
- Authentication via `jsonData.httpHeaderName1` and `secureJsonData.httpHeaderValue1` fields
- No credential storage beyond runtime memory
- Validate all input parameters

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

The current MCP library (v1.12.2) includes `FastMCP` with modern `@tool` decorators that can significantly simplify the implementation:

```python
from mcp.server.fastmcp import FastMCP

app = FastMCP("promesh-mcp")

@app.tool()
def list_datasources() -> list[dict]:
    """List all available Prometheus datasources"""
    # Implementation here
    
@app.tool()
def query_instant(datasource_id: str, promql: str, time: str = None) -> dict:
    """Execute instant PromQL query"""
    # Implementation here
```

**✅ IMPLEMENTED**: The server now uses FastMCP with `@app.tool()` decorators for all 9 tools, providing a much cleaner and more maintainable implementation.

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
- `mcp_tool_requests_total`: Counter by tool name and status
- `mcp_tool_request_duration_seconds`: Histogram by tool name with buckets
- `mcp_server_requests_total`: Counter by HTTP method and endpoint
- `mcp_datasources_configured`: Gauge of configured datasources
- `mcp_connected_clients`: Gauge of active client connections (basic tracking)

**Implementation:**
```python
import structlog
import time

# Configure structured logging with INFO level for visibility
logging.getLogger("fastmcp").setLevel(logging.INFO)
logging.getLogger("mcp").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)  # Keep access logs visible

# Access logging decorator for all MCP tools
def mcp_access_log(tool_name: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            datasource_id = kwargs.get('datasource_id', 'N/A')
            
            logger.info(f"MCP tool called: {tool_name}", 
                       level="INFO", tool=tool_name, datasource=datasource_id)
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"MCP tool completed: {tool_name}",
                           level="INFO", tool=tool_name, datasource=datasource_id,
                           duration_ms=round(duration * 1000, 2), status="success")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"MCP tool failed: {tool_name}",
                            level="ERROR", tool=tool_name, datasource=datasource_id,
                            duration_ms=round(duration * 1000, 2), status="error",
                            error=str(e), error_type=type(e).__name__)
                raise
        return wrapper
    return decorator

# Apply to all tools
@app.tool()
@mcp_access_log("query_instant")
@tool_error_handler
async def query_instant(datasource_id: str, promql: str, time: str | None = None) -> str:
    # Implementation
```

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
- Deployment with configurable resources
- Service exposing port 8000
- ConfigMap mount for datasource configuration at `/etc/grafana/provisioning/datasources/`

**Prerequisites (not included in template):**
```yaml
# Secret containing Grafana datasource YAML files must exist
# Example secret structure:
apiVersion: v1
kind: Secret  
metadata:
  name: prometheus-datasources
type: Opaque
stringData:
  datasources.yaml: |
    apiVersion: 1
    prune: true
    datasources:
      - name: "prod-prometheus"
        type: "prometheus" 
        url: "https://prometheus-prod.example.com"
        jsonData:
          httpHeaderName1: "Authorization"
        secureJsonData:
          httpHeaderValue1: "Bearer <token>"
      - name: "staging-prometheus" 
        type: "prometheus"
        url: "https://prometheus-staging.example.com"
        # ... additional prometheus datasources
      - name: "loki-logs"
        type: "loki"  # Will be ignored by MCP server
        # ... loki configuration
```

## README.md Requirements

### Local Development Section
Must include detailed instructions for:

**Container Development:**
```bash
# Build and run with podman/docker
podman build -t promesh-mcp .

# Create sample datasource config
cat > datasources.yaml << EOF  
apiVersion: 1
prune: true
datasources:
  - name: "local-prometheus"
    type: "prometheus" 
    url: "http://localhost:9090"
    access: "proxy"
    editable: false
  - name: "demo-prometheus"
    type: "prometheus"
    url: "https://demo.robustperception.io:9090"
    access: "proxy"
    editable: false
EOF

# Mount local datasource config
podman run -p 8000:8000 \
  -v ./datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro \
  promesh-mcp

# Test FastMCP server (requires MCP client)
# The server uses streamable HTTP transport for MCP protocol
```

**Development Environment:**
```bash
# Setup with uv
uv sync

# Use Makefile commands
make lint
make test
make run

# Or run directly
PYTHONPATH=. uv run ruff check --fix
PYTHONPATH=. uv run pytest --cov --cov-report=html
uv run python -m promesh_mcp
# Correct way: uv run python -m promesh_mcp
```
