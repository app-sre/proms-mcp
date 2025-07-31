# Local Testing Guide

This document provides examples for testing the Proms MCP server locally using curl and bearer tokens.

## Prerequisites

1. **Start the server locally:**
   ```bash
   # No authentication mode (for development)
   AUTH_MODE=none python -m proms_mcp.server
   
   # Active authentication mode (requires OpenShift token)
   AUTH_MODE=active OPENSHIFT_API_URL=https://api.your-cluster.com:6443 python -m proms_mcp.server
   ```

2. **Get your OpenShift bearer token (for active mode):**
   ```bash
   # Login to OpenShift
   oc login https://api.your-cluster.com:6443
   
   # Get your token
   export TOKEN=$(oc whoami -t)
   echo "Bearer token: $TOKEN"
   ```

## Testing with No Authentication (AUTH_MODE=none)

When running in no-auth mode, you can test all endpoints without authentication:

### Health Check
```bash
curl -X GET http://localhost:8000/health
```

### MCP Protocol Endpoints
```bash
# List tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'

# Call a tool
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

## Testing with Bearer Token Authentication (AUTH_MODE=active)

When running in active mode, all endpoints except `/health` and `/metrics` require authentication.

### Health Check (No auth required)
```bash
curl -X GET http://localhost:8080/health
```

### Metrics (No auth required)
```bash
curl -X GET http://localhost:8080/metrics
```

### MCP Protocol with Bearer Token

The server supports authentication via both Authorization header and query parameter:

#### Using Authorization Header
```bash
# Set your token
export TOKEN="your-openshift-token-here"

# List tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'

#### Using Query Parameter (for Cursor compatibility)
```bash
# Set your token
export TOKEN="your-openshift-token-here"

# List tools with token in URL
curl -X POST "http://localhost:8000/mcp?token=$TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'

# Call list_datasources tool
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "list_datasources",
      "arguments": {}
    }
  }'

# Call query_instant tool
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "query_instant",
      "arguments": {
        "datasource_id": "your-datasource-name",
        "promql": "up"
      }
    }
  }'
```

## Testing Authentication Failures

### Missing Token (should return 401)
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```

Expected response:
```json
{
  "error": "Authentication required"
}
```

### Invalid Token (should return 401)
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer invalid-token" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```



## Common Test Scenarios

### 1. Basic Server Functionality
```bash
# Test server is running
curl -X GET http://localhost:8000/health

# Test metrics endpoint
curl -X GET http://localhost:8000/metrics
```

### 2. Authentication Flow Test
```bash
# Get OpenShift token
TOKEN=$(oc whoami -t)

# Test authenticated request
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }' | jq .
```

### 3. Tool Functionality Test
```bash
# List available datasources
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "list_datasources",
      "arguments": {}
    }
  }' | jq .

# Get metrics from a datasource
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "list_metrics",
      "arguments": {
        "datasource_id": "prometheus-main"
      }
    }
  }' | jq .
```

## Troubleshooting

### 401 Authentication Required
- Verify you're using the correct token: `oc whoami -t`
- Check token is not expired: `oc whoami`
- Ensure you're including the `Authorization: Bearer` header
- Verify AUTH_MODE is set correctly

### Connection Refused
- Check server is running: `ps aux | grep proms_mcp`
- Verify port is correct (default 8000)
- Check server logs for errors

### Invalid JSON-RPC
- Ensure Content-Type is `application/json`
- Verify JSON syntax is valid
- Check method names match available tools



## Cursor Configuration

To use the server with Cursor IDE, configure your `.cursor/mcp.json` file:

### For Active Authentication Mode
```json
{
  "mcpServers": {
    "proms-mcp": {
      "url": "http://localhost:8000/mcp?token=your-openshift-token-here",
      "description": "Proms MCP Server with OpenShift authentication"
    }
  }
}
```

### For No-Auth Mode
```json
{
  "mcpServers": {
    "proms-mcp-dev": {
      "url": "http://localhost:8000/mcp",
      "description": "Proms MCP Server - no authentication"
    }
  }
}
```

**Note**: Cursor does not currently support the `headers` field for SSE connections, so the token must be passed in the URL query parameter when using active authentication mode.

## Environment Variables

Key environment variables for testing:

```bash
# Authentication mode
export AUTH_MODE=none          # No authentication (dev only)
export AUTH_MODE=active        # OpenShift bearer token auth

# OpenShift configuration (for active mode)
export OPENSHIFT_API_URL=https://api.your-cluster.com:6443
export OPENSHIFT_CA_CERT_PATH=/path/to/ca.crt  # Optional
export OPENSHIFT_SSL_VERIFY=true               # Optional, default true

# Server configuration
export HOST=127.0.0.1          # Default
export PORT=8000               # Default
export GRAFANA_DATASOURCES_PATH=/path/to/datasources.yaml
``` 
