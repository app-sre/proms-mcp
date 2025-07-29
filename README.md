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

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management
- Docker/Podman for container development

### Local Development

```bash
# Clone and setup
git clone <repository-url>
cd promesh-mcp
make install

# Run the server
make run
# Or: uv run python -m promesh_mcp
```

### Container Development

```bash
# Build container
podman build -t promesh-mcp .

# Create datasource config (see Configuration section)
# Run with config
podman run -p 8000:8000 \
  -v ./datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro \
  promesh-mcp
```

## MCP Client Setup

### Cursor Integration

Add to your Cursor settings (`Cursor Settings > Features > Rules for AI` or `.cursor/mcp.json` in your workspace):

```json
{
  "mcpServers": {
    "promesh-mcp": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Other MCP Clients

The server exposes MCP over HTTP at:
- **Endpoint**: `POST http://localhost:8000/mcp`
- **Protocol**: JSON-RPC 2.0 over HTTP
- **Content-Type**: `application/json`
- **Accept**: `application/json, text/event-stream`

## Configuration

### Environment Variables

- `PORT`: MCP server port (default: 8000)
- `HEALTH_METRICS_PORT`: Health and metrics server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)
- `GRAFANA_DATASOURCES_PATH`: Path to datasource config file (default: /etc/grafana/provisioning/datasources/datasources.yaml)
- `QUERY_TIMEOUT`: Query timeout in seconds (default: 30)
- `SHUTDOWN_TIMEOUT_SECONDS`: Graceful shutdown timeout in seconds (default: 8)

### Datasource Configuration

Create a Grafana datasource provisioning YAML file. Only `type: "prometheus"` datasources are processed.

**Example datasources.yaml:**
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
  - name: "demo-prometheus"
    type: "prometheus"
    url: "https://demo.robustperception.io:9090"
    access: "proxy"
    editable: false
```

## Security

### PromQL Query Validation

The server implements basic security checks:
- **Query Length**: Limits to 10,000 characters
- **Empty Query**: Prevents empty or whitespace-only queries
- **Input Sanitization**: Basic parameter encoding via httpx

## Production Deployment

### OpenShift

```bash
# Create datasource secret
oc create secret generic prometheus-datasources \
  --from-file=datasources.yaml=path/to/your/datasources.yaml

# Deploy
oc process -f openshift/deploy.yaml \
  -p IMAGE=your-registry/promesh-mcp \
  -p IMAGE_TAG=v1.0.0 | oc apply -f -
```

## API Endpoints

- **POST /mcp**: MCP JSON-RPC 2.0 endpoint (port 8000)
- **GET /health**: Health check (port 8080)
- **GET /metrics**: Prometheus metrics (port 8080)

## Development

### Code Quality
```bash
make format          # Format code and fix imports
make lint            # Lint and type check code
make test            # Run tests with coverage
```

### Project Structure
```
promesh-mcp/
  promesh_mcp/           # Main package
    server.py            # FastMCP server
    client.py            # Prometheus API wrapper
    config.py            # Config parser
    monitoring.py        # Health/metrics endpoints
  tests/                 # Test suite
  openshift/deploy.yaml  # OpenShift template
```

## Troubleshooting

### Common Issues

1. **No datasources loaded**: Check `GRAFANA_DATASOURCES_PATH` and YAML syntax
2. **Authentication failures**: Verify bearer tokens in `secureJsonData`
3. **Query timeouts**: Adjust `QUERY_TIMEOUT` environment variable
4. **Query validation errors**: Check query length and ensure non-empty queries
5. **Client connection issues**: 
   - **400 Bad Request**: Server restart - client will reconnect automatically
   - **406 Not Acceptable**: Client must accept `application/json, text/event-stream`

### Debug Mode
```bash
LOG_LEVEL=DEBUG make run
```

### Health Checks
```bash
curl http://localhost:8080/health
curl http://localhost:8080/metrics | grep mcp_
```

## Documentation

- **[SPECS.md](SPECS.md)** - Technical specification and architecture
- **[LLM.md](LLM.md)** - Development guide for AI assistants

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run quality checks: `make format lint test`
5. Submit a pull request

## License

Apache License 2.0 
