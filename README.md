# Promesh MCP Server

A lean MCP (Model Context Protocol) server that provides LLM agents with transparent access to multiple Prometheus instances for metrics analysis and SRE operations.

## Overview

This server implements the MCP protocol using the modern FastMCP library, allowing LLM agents to query multiple Prometheus instances through a unified interface. It supports discovery, querying, and analysis of Prometheus metrics with built-in security validation and comprehensive observability.

## Features

- **Multiple Prometheus Support**: Query multiple Prometheus instances through a single interface
- **Security Hardening**: Basic PromQL query validation for safety
- **Comprehensive Toolset**: 8 MCP tools covering discovery, querying, and analysis using modern `@tool` decorators
- **Observability**: Structured logging for debugging and monitoring
- **Production Ready**: Designed for OpenShift/Kubernetes deployment
- **Lean Architecture**: Stateless, minimal dependencies (5 core dependencies), fail-fast design

## MCP Tools

### Discovery Tools
- `list_datasources`: List all available Prometheus datasources
- `list_metrics`: Get all available metric names from a datasource
- `get_metric_metadata`: Get metadata for a specific metric

### Query Tools
- `query_instant`: Execute instant PromQL query
- `query_range`: Execute range PromQL query

### Analysis Tools
- `get_metric_labels`: Get all label names for a specific metric
- `get_label_values`: Get all values for a specific label
- `find_metrics_by_pattern`: Find metrics matching a regex pattern

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management
- Docker/Podman for container development

### Development Environment Setup

```bash
# Clone the repository
git clone <repository-url>
cd promesh-mcp

# Install dependencies
make install

# Run linting and formatting
make format
make lint

# Run tests with coverage
make test

# Start FastMCP server
make run

# Or run directly
uv run python -m promesh_mcp
```

### Container Development

#### Build and Run with Docker/Podman

```bash
# Build the container
podman build -t promesh-mcp .

# Create sample datasource configuration
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

# Run with mounted datasource config
podman run -p 8000:8000 \
  -v ./datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro \
  promesh-mcp

# Test FastMCP endpoint (using MCP client or test tools)
# The FastMCP server uses streamable HTTP transport for MCP protocol
```

#### Test with Multiple Datasources

```bash
# Create multi-datasource configuration
cat > datasources.yaml << EOF
apiVersion: 1
prune: true
datasources:
  - name: "prometheus-1"
    type: "prometheus"
    url: "https://demo.robustperception.io:9090"
    access: "proxy"
    editable: false
  - name: "prometheus-2"
    type: "prometheus"
    url: "http://localhost:9090"
    access: "proxy"
    editable: false
    jsonData:
      httpHeaderName1: "Authorization"
    secureJsonData:
      httpHeaderValue1: "Bearer your-token-here"
  - name: "loki-logs"
    type: "loki"  # Will be ignored by MCP server
    url: "http://localhost:3100"
EOF

# Run container
podman run -p 8000:8000 \
  -v ./datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro \
  promesh-mcp
```

### Testing the Server

#### Health Check
```bash
curl http://localhost:8080/health
```

#### List Available Tools
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```

#### List Datasources
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "list_datasources",
      "arguments": {}
    }
  }'
```

#### Query Metrics
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "query_instant",
      "arguments": {
        "datasource_id": "demo-prometheus",
        "promql": "up"
      }
    }
  }'
```

#### View Metrics
```bash
curl http://localhost:8080/metrics
```

## Configuration

### Environment Variables

- `PORT`: MCP server port (default: 8000)
- `HEALTH_METRICS_PORT`: Health and metrics server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)
- `GRAFANA_DATASOURCES_PATH`: Path to datasource config file (default: /etc/grafana/provisioning/datasources/datasources.yaml)
- `QUERY_TIMEOUT`: Query timeout in seconds (default: 30)
- `SHUTDOWN_TIMEOUT_SECONDS`: Graceful shutdown timeout in seconds (default: 8)

### Datasource Configuration

The server loads Prometheus datasources from a single Grafana datasource provisioning YAML file. Only datasources with `type: "prometheus"` are processed.

#### Example Datasource Configuration

```yaml
apiVersion: 1
prune: true
datasources:
  - name: "prod-prometheus"
    type: "prometheus"
    url: "https://prometheus-prod.example.com"
    access: "proxy"
    editable: false
    jsonData:
      httpHeaderName1: "Authorization"
    secureJsonData:
      httpHeaderValue1: "Bearer prod-token"
  - name: "staging-prometheus"
    type: "prometheus"
    url: "https://prometheus-staging.example.com"
    access: "proxy"
    editable: false
    # No authentication required
  - name: "loki-logs"
    type: "loki"  # Will be ignored
    url: "https://loki.example.com"
```

## Security

### PromQL Query Validation

The server implements security checks to prevent dangerous queries:

- **Long Range Queries**: Blocks queries with very long time ranges (minutes, years, weeks)
- **Regex DoS**: Prevents regex patterns that could cause denial of service
- **Query Length**: Limits query length to 10,000 characters
- **Allowed Ranges**: Hours (`h`) and days (`d`) are permitted for legitimate analysis

### Examples of Blocked Queries

```promql
rate(metric[1y])        # Year range - blocked
rate(metric[60m])       # Minute range - blocked  
{job=~".*"*}           # Regex DoS - blocked
metric[999999s]        # Extremely large range - blocked
```

### Examples of Allowed Queries

```promql
rate(metric[5h])       # Hour range - allowed
rate(metric[2d])       # Day range - allowed
up                     # Simple query - allowed
sum(rate(cpu[1h]))     # Complex but safe - allowed
```

## Production Deployment

### OpenShift Deployment

The server includes an OpenShift template for production deployment:

```bash
# Process and apply the template
oc process -f openshift/deploy.yaml \
  -p IMAGE=your-registry/promesh-mcp \
  -p IMAGE_TAG=v1.0.0 \
  -p MEMORY_REQUEST=256Mi \
  -p MEMORY_LIMIT=512Mi \
  -p CPU_REQUEST=100m | oc apply -f -
```

### Prerequisites for Production

Create a secret containing your Grafana datasource configuration:

```bash
# Create secret with datasource configuration
oc create secret generic prometheus-datasources \
  --from-file=datasources.yaml=path/to/your/datasources.yaml
```

### Template Parameters

- `IMAGE`: Container image name (required)
- `IMAGE_TAG`: Git commit SHA (required)
- `MEMORY_REQUEST`: Memory request (default: 256Mi)
- `MEMORY_LIMIT`: Memory limit (default: 512Mi)
- `CPU_REQUEST`: CPU request (default: 100m)

## API Endpoints

### MCP over HTTP
- **POST /mcp**: MCP JSON-RPC 2.0 endpoint
- **Content-Type**: application/json

### Health and Monitoring
- **GET /health**: Health check endpoint (port 8080)
- **GET /metrics**: Prometheus metrics endpoint (port 8080)

## Monitoring

The server exposes the following Prometheus metrics:

- `mcp_tool_requests_total`: Counter of MCP tool requests by tool, datasource, and status
- `mcp_tool_request_duration_seconds`: Histogram of MCP tool request durations
- `mcp_server_requests_total`: Counter of HTTP requests by method, endpoint, and status
- `mcp_datasources_configured`: Gauge of configured Prometheus datasources

## Development Workflow

### Code Quality

```bash
# Run all quality checks
make format          # Format code and fix imports
make lint            # Lint and type check code
make test            # Run tests with coverage
```

### Project Structure

```
promesh-mcp/
  promesh_mcp/           # Main package directory
    server.py            # Main FastMCP server
    client.py            # Prometheus API wrapper
    config.py            # Grafana YAML config parser
    monitoring.py        # Health and metrics endpoints
  tests/                 # Test suite (separate from package)
    test_*.py            # Unit and integration tests
  openshift/
    deploy.yaml          # OpenShift deployment template
  pyproject.toml         # Package configuration
  Dockerfile             # Container definition
  README.md              # This file
```

### Testing

The project includes comprehensive tests with >95% coverage:

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test HTTP endpoints and MCP protocol
- **Mock Testing**: Test with mock Prometheus responses
- **Error Handling**: Test all error conditions and edge cases

```bash
# Run specific test categories
PYTHONPATH=. uv run pytest tests/test_config.py -v
PYTHONPATH=. uv run pytest tests/test_client.py -v
PYTHONPATH=. uv run pytest tests/test_server_fastmcp.py -v

# Run with coverage report
make test
# View coverage report in htmlcov/index.html
```

## Troubleshooting

### Common Issues

1. **No datasources loaded**
   - Check `GRAFANA_DATASOURCES_PATH` environment variable
   - Verify YAML file exists and contains `type: "prometheus"` datasources
   - Check server logs for parsing errors

2. **Authentication failures**
   - Verify `jsonData.httpHeaderName1` and `secureJsonData.httpHeaderValue1` are set correctly
   - Check that bearer tokens are valid and have proper permissions

3. **Query timeouts**
   - Adjust `QUERY_TIMEOUT` environment variable
   - Check Prometheus instance performance
   - Verify network connectivity

4. **Dangerous query errors**
   - Review PromQL query for blocked patterns
   - Use hours (`h`) or days (`d`) instead of minutes (`m`), years (`y`), or weeks (`w`)
   - Avoid regex patterns with wildcards in label selectors

5. **Client connection issues (400/406 errors)**
   
   **400 Bad Request**: Usually occurs when clients (like Cursor) attempt to reconnect immediately after server restart with stale connection state. Wait a few seconds and try reconnecting.
   
   **406 Not Acceptable**: Occurs when the client doesn't send the correct `Accept` headers. MCP over Streamable HTTP requires clients to accept both:
   - `application/json` 
   - `text/event-stream`
   
   Example of correct headers:
   ```bash
   curl -X POST http://localhost:8000/mcp \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc": "2.0", "method": "initialize", "id": 1}'
   ```
   
   For debugging connection issues, the server now logs detailed request/response information when errors occur.

### Debug Mode

Enable debug logging:

```bash
LOG_LEVEL=DEBUG make run
```

### Health Checks

The server provides comprehensive health checks:

```bash
# Check overall health
curl http://localhost:8080/health

# Check metrics for detailed status
curl http://localhost:8080/metrics | grep mcp_
```

## Documentation

This project includes comprehensive documentation for different audiences:

- **[README.md](README.md)** - This file: User guide, setup, and usage instructions
- **[SPECS.md](SPECS.md)** - Technical specification and architecture details for developers
- **[LLM.md](LLM.md)** - Development guide for LLMs and AI assistants working on the codebase
- **[GEMINI.md](GEMINI.md)** - Gemini-specific integration notes and considerations

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run quality checks: `make qa` (includes lint, format, type-check, and test)
5. Submit a pull request

Please review [LLM.md](LLM.md) for detailed development guidelines and best practices.

## License

This project is licensed under the Apache License 2.0. 
