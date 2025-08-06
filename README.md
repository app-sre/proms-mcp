# Proms MCP Server

A lean MCP (Model Context Protocol) server that provides LLM agents with transparent access to multiple Prometheus instances for metrics analysis and SRE operations.

## Overview

This server implements the MCP protocol using the modern FastMCP library, allowing LLM agents to query multiple Prometheus instances through a unified interface. It supports discovery, querying, and analysis of Prometheus metrics with built-in security validation and comprehensive observability.

## Features

- **Multiple Prometheus Support**: Query multiple Prometheus instances through a single interface
- **Bearer Token Authentication**: Secure authentication using OpenShift bearer tokens
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
cd proms-mcp
make install

# Create datasource configuration
cp local_config/datasources-example.yaml local_config/datasources.yaml
# Edit local_config/datasources.yaml with your Prometheus instances

# Run the server (no authentication - recommended for development)
make run
```

**Authenticated mode** (for testing with OpenShift auth):

```bash
# Run with OpenShift authentication
make run-auth OPENSHIFT_API_URL=https://api.cluster.example.com:6443
```

**Manual startup** (if not using make):

```bash
# Development mode (no authentication)
export AUTH_MODE=none
export GRAFANA_DATASOURCES_PATH=local_config/datasources.yaml
uv run python -m proms_mcp

# Authenticated mode
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.cluster.example.com:6443
export GRAFANA_DATASOURCES_PATH=local_config/datasources.yaml
uv run python -m proms_mcp
```

### Container Development

```bash
# Build container
podman build -t proms-mcp .

# Create datasource config (see Configuration section)
# Run with config
podman run -p 8000:8000 \
  -v ./datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro \
  proms-mcp
```

## MCP Client Setup

### Cursor Integration

The server supports two authentication modes:

**Development (No Authentication):**

```json
{
  "mcpServers": {
    "proms-mcp-dev": {
              "url": "http://localhost:8000/mcp/",
      "description": "Development server - no authentication"
    }
  }
}
```

**Production (Bearer Token Authentication):**

```json
{
  "mcpServers": {
    "proms-mcp": {
      "url": "https://proms-mcp.apps.cluster.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-openshift-token-here"
      },
      "description": "Production server with OpenShift bearer token auth"
    }
  }
}
```

> ⚠️ **Security Note**: Never commit `.cursor/mcp.json` with real tokens to git. It's already in `.gitignore`.

See `.cursor/mcp-examples.json` for complete configuration examples including:

- Development and production setups
- Service account token configuration
- Multi-environment configurations
- SSL verification scenarios

### Other MCP Clients

The server exposes MCP over HTTP at:

- **Endpoint**: `POST http://localhost:8000/mcp/` (or your deployed URL)
- **Protocol**: JSON-RPC 2.0 over HTTP
- **Content-Type**: `application/json`
- **Accept**: `application/json, text/event-stream`
- **Authentication**: Bearer token in `Authorization` header (when `AUTH_MODE=active`)

> 📝 **Path Behavior**: The server uses `/mcp/` (with trailing slash) to avoid HTTP 307 redirects that can cause authentication issues in some MCP clients. Always use the trailing slash in your client configurations.

## Configuration

### Environment Variables

- `PORT`: MCP server port (default: 8000)
- `HEALTH_METRICS_PORT`: Health and metrics server port (default: 8080)
- `LOG_LEVEL`: Logging level (default: INFO)
- `GRAFANA_DATASOURCES_PATH`: Path to datasource config file (default: /etc/grafana/provisioning/datasources/datasources.yaml)
- `QUERY_TIMEOUT`: Query timeout in seconds (default: 30)
- `SHUTDOWN_TIMEOUT_SECONDS`: Graceful shutdown timeout in seconds (default: 8)

### Authentication Configuration

The server supports two authentication modes:

- `AUTH_MODE`: Authentication mode (`none` or `active`, default: `active`)
- `OPENSHIFT_API_URL`: OpenShift API server URL (required for bearer token auth)
- `OPENSHIFT_SERVICE_ACCOUNT_TOKEN`: Service account token for API calls (for local development)
- `OPENSHIFT_CA_CERT_PATH`: Path to CA certificate file for SSL verification (optional, only needed for custom certificates)
- `OPENSHIFT_SSL_VERIFY`: Enable/disable SSL verification (`true`/`false`, default: `true`)
- `AUTH_CACHE_TTL_SECONDS`: Authentication cache TTL in seconds (default: 300)

#### No Authentication Mode (Development Only)

```bash
# Explicitly disable authentication for development
AUTH_MODE=none uv run python -m proms_mcp
```

#### Bearer Token Authentication Mode (Default)

```bash
# Get your OpenShift token
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t)

# Run with bearer token authentication
AUTH_MODE=active \
OPENSHIFT_API_URL=https://api.cluster.example.com:6443 \
OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$OPENSHIFT_SERVICE_ACCOUNT_TOKEN \
uv run python -m proms_mcp

# For self-signed certificates, you can:
# 1. Disable SSL verification (INSECURE - development only):
OPENSHIFT_SSL_VERIFY=false uv run python -m proms_mcp

# 2. Or provide the CA certificate (if needed for custom certificates):
OPENSHIFT_CA_CERT_PATH=/path/to/ca.crt uv run python -m proms_mcp
```

**Required RBAC for Bearer Token Authentication:**
The server requires the `system:auth-delegator` ClusterRole to validate OpenShift tokens.

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

## API Endpoints

- **POST /mcp/**: MCP JSON-RPC 2.0 endpoint (port 8000)
- **GET /health**: Health check (port 8080)
- **GET /metrics**: Prometheus metrics (port 8080)

## Deployment

### OpenShift Deployment

Deploy using the provided OpenShift template:

```bash
# Development deployment (no authentication)
oc process -f openshift/deploy.yaml \
  -p IMAGE=quay.io/app-sre/proms-mcp \
  -p IMAGE_TAG=latest \
  -p AUTH_MODE=none \
  | oc apply -f -

# Production deployment (bearer token authentication)
oc process -f openshift/deploy.yaml \
  -p IMAGE=quay.io/app-sre/proms-mcp \
  -p IMAGE_TAG=v1.0.0 \
  -p AUTH_MODE=active \
  -p OPENSHIFT_API_URL=https://api.cluster.example.com:6443 \
  | oc apply -f -

# For bearer token authentication, also create the required ClusterRoleBinding:
oc create clusterrolebinding proms-mcp-auth-delegator \
  --clusterrole=system:auth-delegator \
  --serviceaccount=$(oc project -q):proms-mcp-server
```

**Template Parameters:**

- `AUTH_MODE`: `none` (development) or `active` (production)
- `OPENSHIFT_API_URL`: Required for bearer token authentication mode
- `AUTH_CACHE_TTL_SECONDS`: Token validation cache TTL (default: 300)

### MCP Client Configuration

#### Development Mode (No Authentication)

```json
{
  "mcpServers": {
    "proms-mcp-dev": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

#### Production Mode (Bearer Token)

```json
{
  "mcpServers": {
    "proms-mcp": {
      "url": "https://proms-mcp.apps.cluster.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${OPENSHIFT_TOKEN}"
      }
    }
  }
}
```

Get your OpenShift token:

```bash
export OPENSHIFT_TOKEN=$(oc whoami -t)
```

### RBAC Requirements

For production (bearer token authentication) deployments, the server requires:

1. **ServiceAccount**: `proms-mcp-server` (created by template)
2. **ClusterRoleBinding**: Uses `system:auth-delegator` ClusterRole for token validation (must be created separately)
3. **User Tokens**: Users need valid OpenShift tokens (`oc whoami -t`)

The template creates the ServiceAccount. The ClusterRoleBinding must be created separately using the command shown above.

## Development

### Code Quality

```bash
make format          # Format code and fix imports
make lint            # Lint and type check code
make test            # Run tests with coverage
```

### Project Structure

```
proms-mcp/
  proms_mcp/             # Main package
    auth/                  # Authentication module
      __init__.py            # AuthMode enum, User model, exports
      cache.py               # Token caching for performance
      fastmcp_auth.py        # FastMCP OpenShiftTokenVerifier integration
      openshift.py           # OpenShift API client
    server.py              # FastMCP server
    client.py              # Prometheus API wrapper
    config.py              # Config parser with auth support
    monitoring.py          # Health/metrics endpoints
  tests/                   # Test suite
    auth/                    # Authentication tests
  openshift/deploy.yaml    # OpenShift template with auth support
  .cursor/mcp.json         # MCP client configuration examples
```

## Troubleshooting

### Common Issues

1. **No datasources loaded**:
   - Check that `GRAFANA_DATASOURCES_PATH` points to your datasources file
   - Verify YAML syntax is valid (JSON format is also supported)
   - Ensure the file contains a `datasources` array with `type: "prometheus"` entries
   - Use `make run` which automatically sets the path to `local_config/datasources.yaml`
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
- **[TESTING.md](TESTING.md)** - Local testing guide with bearer token examples

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run quality checks: `make format lint test`
5. Submit a pull request

## License

Apache License 2.0
