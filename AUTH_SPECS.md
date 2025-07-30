# Authentication Specifications for Proms MCP Server

## Overview

This document outlines the authentication implementation for the Proms MCP server, supporting two authentication modes to accommodate different deployment scenarios and user workflows.

**Key Design Decisions**:
- **Two modes only**: `none` (development) and `active` (production)
- **No API key management**: Focus on OpenShift bearer token and OAuth integration
- **Namespace-scoped RBAC**: Use `system:auth-delegator` ClusterRole for token validation
- **Unified active mode**: Single mode supporting both bearer tokens and OAuth (phased implementation)

## Authentication Methods Comparison

### Authentication Methods

The server supports two authentication modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **none** | No authentication required | Local development and testing |
| **active** | OpenShift bearer token validation | Production deployment |

In **active** mode, the server supports:
- **Phase 1**: Bearer token validation against OpenShift API
- **Phase 2**: OAuth 2.1 integration with fallback to bearer tokens

### OpenShift Token Types

**User Tokens** (from `oc whoami -t`):
- Generated when user logs in via `oc login`
- Expire after 24 hours (default)
- Contain user identity and group memberships
- Validated against OpenShift API server

**Service Account Tokens**:
- Long-lived tokens for automation
- Don't expire (unless SA is deleted)
- Contain service account identity
- Also validated against OpenShift API server

Both are "bearer tokens" but with different lifecycles.

## Implementation Phases

### Phase 1: No-Auth Mode (1 week)
**Purpose**: Local development and testing

**Features**:
- Completely disable authentication
- Environment variable controlled: `AUTH_MODE=none`
- Mock user context for logging
- Not available in production builds

**Implementation Steps**:
1. Create `AuthMode` enum and configuration
2. Implement `NoAuthBackend` class
3. Add middleware bypass logic
4. Update server initialization
5. Add environment variable validation
6. Create unit tests

**Code Structure**:
```python
# proms_mcp/auth/__init__.py
from enum import Enum

class AuthMode(Enum):
    NONE = "none"
    BEARER_TOKEN = "bearer-token"
    OPENSHIFT_OAUTH = "openshift-oauth"
    MULTI = "multi"

# proms_mcp/auth/backends.py
class NoAuthBackend:
    async def authenticate(self, request):
        return MockUser(username="dev-user", groups=["developers"])
```

### Phase 2: Active Authentication - Bearer Token (2-3 weeks)
**Purpose**: Production authentication for users and service accounts

**Features**:
- Validate OpenShift bearer tokens against API server
- Support both user tokens and service account tokens
- Token caching to reduce API calls
- Graceful handling of expired tokens
- User identity and group extraction

**Implementation Steps**:

#### Step 1: OpenShift Client Setup
1. Create `OpenShiftClient` class for API communication
2. Implement token validation endpoint calls
3. Add service account token mounting
4. Configure RBAC permissions

#### Step 2: Bearer Token Backend
1. Create `BearerTokenBackend` class
2. Implement token extraction from Authorization header
3. Add token validation logic
4. Implement user/service account detection
5. Add caching layer (5-minute TTL)

#### Step 3: Integration
1. Add authentication middleware to FastMCP
2. Update server initialization
3. Add proper error handling and logging
4. Create comprehensive unit tests

**Required OpenShift RBAC**:

The server requires token validation capabilities. We use namespace-scoped permissions where possible.

**Recommended Approach**: Use the built-in `system:auth-delegator` ClusterRole which provides the necessary permissions for token validation without requiring custom cluster-wide permissions.

```yaml
# Option 1: Namespace-scoped with system:auth-delegator (Recommended)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: proms-mcp-auth-delegator
subjects:
- kind: ServiceAccount
  name: proms-mcp-server
  namespace: your-namespace
roleRef:
  kind: ClusterRole
  name: system:auth-delegator
  apiGroup: rbac.authorization.k8s.io

---
# Namespace-scoped role for local resources if needed
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: your-namespace
  name: proms-mcp-local
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: proms-mcp-local
  namespace: your-namespace
subjects:
- kind: ServiceAccount
  name: proms-mcp-server
  namespace: your-namespace
roleRef:
  kind: Role
  name: proms-mcp-local
  apiGroup: rbac.authorization.k8s.io
```

**Alternative (if system:auth-delegator is not available)**:
```yaml
# Option 2: Minimal cluster role for user validation only
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: proms-mcp-auth-minimal
rules:
- apiGroups: ["user.openshift.io"]
  resources: ["users"]
  verbs: ["get"]
- apiGroups: ["authentication.k8s.io"]
  resources: ["tokenreviews"]
  verbs: ["create"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: proms-mcp-auth-minimal
subjects:
- kind: ServiceAccount
  name: proms-mcp-server
  namespace: your-namespace
roleRef:
  kind: ClusterRole
  name: proms-mcp-auth-minimal
  apiGroup: rbac.authorization.k8s.io
```

**Code Structure**:
```python
# proms_mcp/auth/openshift.py
class OpenShiftClient:
    async def validate_token(self, token: str) -> UserInfo | None:
        # Call /apis/user.openshift.io/v1/users/~
        pass

class BearerTokenBackend:
    async def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        return await self.openshift_client.validate_token(token)
```

### Bearer Token Authentication Scenarios

The bearer token authentication supports multiple deployment scenarios with flexible SSL and API configuration options:

#### Scenario 1: Development with SSL Verification Disabled

**Use Case**: Local development against self-signed or untrusted certificates

**Configuration**:
```bash
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.cluster.example.com:6443
export OPENSHIFT_SSL_VERIFY=false  # Disable SSL verification (INSECURE)
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t)
```

**Security Warning**: This is insecure and should only be used for development. SSL verification is disabled, making the connection vulnerable to man-in-the-middle attacks.

#### Scenario 2: Production with Public Certificates (Default)

**Use Case**: Production deployment where OpenShift cluster uses valid LetsEncrypt or other trusted certificates

**Configuration**:
```bash
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.cluster.example.com:6443
# OPENSHIFT_SSL_VERIFY defaults to "true"
# No custom CA certificate needed - uses system CA bundle
```

**Features**:
- Uses system CA bundle for certificate validation
- Works with standard trusted certificates (LetsEncrypt, DigiCert, etc.)
- Default and recommended configuration for most deployments

#### Scenario 3: Custom CA Certificate

**Use Case**: OpenShift cluster with custom or internal CA certificates

**Configuration**:
```bash
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.cluster.example.com:6443
export OPENSHIFT_CA_CERT_PATH=/path/to/custom-ca.crt
export OPENSHIFT_SSL_VERIFY=true  # Optional, defaults to true
```

**CA Certificate Extraction** (if needed):
```bash
# Extract CA from current kubeconfig context
kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > custom-ca.crt

# Or extract from OpenShift configmap (if accessible)
oc get cm kube-apiserver-server-ca -n openshift-kube-apiserver -o jsonpath="{.data.ca-bundle\.crt}" > custom-ca.crt
```

#### Scenario 4: In-Pod Deployment with Internal API

**Use Case**: Server running inside OpenShift cluster using internal Kubernetes API

**Configuration**:
```bash
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://kubernetes.default.svc:443  # Internal Kubernetes API
# Service account token automatically mounted at default path
# CA certificate automatically available at /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

**Kubernetes Mounts** (automatic in pods):
- Service Account Token: `/var/run/secrets/kubernetes.io/serviceaccount/token`
- CA Certificate: `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt`
- Namespace: `/var/run/secrets/kubernetes.io/serviceaccount/namespace`

**Deployment Example**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: proms-mcp-server
spec:
  template:
    spec:
      serviceAccountName: proms-mcp-server
      containers:
      - name: proms-mcp
        image: proms-mcp:latest
        env:
        - name: AUTH_MODE
          value: "active"
        - name: OPENSHIFT_API_URL
          value: "https://kubernetes.default.svc:443"
        # No need to set CA cert path - uses mounted ca.crt automatically
        # No need to set service account token - uses mounted token automatically
```

#### Scenario 5: External API with Service Account Token

**Use Case**: Server running outside cluster but using service account authentication

**Configuration**:
```bash
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.cluster.example.com:6443
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN_PATH=/path/to/service-account-token
export OPENSHIFT_CA_CERT_PATH=/path/to/ca.crt  # If needed for custom certs
```

**Service Account Token Creation**:
```bash
# Create service account
oc create serviceaccount proms-mcp-external

# Create token secret
oc create secret generic proms-mcp-token --type=kubernetes.io/service-account-token
oc patch secret proms-mcp-token -p '{"metadata":{"annotations":{"kubernetes.io/service-account.name":"proms-mcp-external"}}}'

# Extract token
oc get secret proms-mcp-token -o jsonpath='{.data.token}' | base64 -d > service-account-token
```

### SSL Configuration Details

#### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `OPENSHIFT_SSL_VERIFY` | `true`, `false` | `true` | Enable/disable SSL certificate verification |
| `OPENSHIFT_CA_CERT_PATH` | File path | None | Path to custom CA certificate file |

#### SSL Verification Behavior

1. **Custom CA Certificate Priority**: If `OPENSHIFT_CA_CERT_PATH` is set and file exists, it takes priority over `OPENSHIFT_SSL_VERIFY`
2. **System CA Bundle**: When `OPENSHIFT_SSL_VERIFY=true` (default) and no custom CA, uses system CA bundle
3. **Disabled Verification**: When `OPENSHIFT_SSL_VERIFY=false`, all certificate validation is skipped (insecure)

#### Code Implementation

```python
def _get_ssl_verify_config(self) -> bool | str:
    """Get SSL verification configuration.
    
    When running within a pod, OpenShift clusters typically have valid 
    LetsEncrypt certificates accessible from outside, and the default 
    system CA bundle should handle verification correctly.

    Returns:
        - False: Disable SSL verification (insecure, for development only)
        - True: Use system CA bundle (default, works with LetsEncrypt certs)
        - str: Path to custom CA certificate file (only needed for custom certs)
    """
    # Check environment variable for SSL verification control
    ssl_verify_env = os.getenv("OPENSHIFT_SSL_VERIFY", "true").lower()

    if ssl_verify_env == "false":
        logger.warning(
            "SSL certificate verification disabled - this is insecure and should only be used for development"
        )
        return False

    # If CA cert path is provided, use it
    if self.ca_cert_path and os.path.exists(self.ca_cert_path):
        logger.info("Using custom CA certificate", ca_cert_path=self.ca_cert_path)
        return self.ca_cert_path

    # Default to system CA bundle
    return True
```

### Phase 3: Active Authentication - OAuth Integration (3-4 weeks)
**Purpose**: Enhanced user experience with automatic token refresh

**Features**:
- OAuth 2.1 with PKCE support
- Browser-based authentication flow
- Automatic token refresh
- Dynamic client registration
- Fallback to bearer token validation
- Unified "active" mode supporting both methods

**Implementation Steps**:

#### Step 1: OAuth Provider Setup
1. Register OAuth client in OpenShift
2. Configure redirect URIs and scopes
3. Set up OAuth endpoints discovery
4. Create OAuth client credentials secret

#### Step 2: OAuth Backend Implementation
1. Create `OAuthBackend` class
2. Implement authorization URL generation
3. Add callback endpoint handling
4. Implement token exchange (code for token)
5. Add token refresh logic

#### Step 3: FastMCP Integration
1. Add OAuth routes to FastMCP server
2. Implement OAuth middleware
3. Add client-side OAuth support detection
4. Create OAuth flow documentation

#### Step 4: Unified Active Auth Support
1. Update `ActiveAuthBackend` class to support both bearer tokens and OAuth
2. Implement authentication chain logic (bearer token → OAuth fallback)
3. Add fallback mechanisms
4. Maintain single "active" mode configuration

**OAuth Configuration**:
```yaml
# OpenShift OAuth Client
apiVersion: oauth.openshift.io/v1
kind: OAuthClient
metadata:
  name: proms-mcp-client
redirectURIs:
- "https://proms-mcp.apps.cluster.example.com/oauth/callback"
grantMethod: auto
```

**Code Structure**:
```python
# proms_mcp/auth/oauth.py
class OAuthBackend:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.openshift_oauth_url = "https://oauth-openshift.apps.cluster.example.com"
    
    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        # Generate OAuth authorization URL
        pass
    
    async def exchange_code_for_token(self, code: str, code_verifier: str):
        # Exchange authorization code for access token
        pass

# proms_mcp/auth/active.py
class ActiveAuthBackend:
    def __init__(self, bearer_backend: BearerTokenBackend, oauth_backend: OAuthBackend = None):
        self.bearer_backend = bearer_backend
        self.oauth_backend = oauth_backend
    
    async def authenticate(self, request):
        # Try bearer token first
        result = await self.bearer_backend.authenticate(request)
        if result:
            return result
        
        # Try OAuth if available (Phase 3)
        if self.oauth_backend:
            result = await self.oauth_backend.authenticate(request)
            if result:
                return result
        
        return None
```

## Configuration System

### Environment Variables

```python
# Authentication configuration
AUTH_MODE = "none" | "active"  # Default: "active"

# OpenShift API configuration
OPENSHIFT_API_URL = "https://api.cluster.example.com:6443"
OPENSHIFT_SERVICE_ACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

# SSL/TLS configuration
OPENSHIFT_SSL_VERIFY = "true" | "false"  # Default: "true"
OPENSHIFT_CA_CERT_PATH = "/path/to/custom-ca.crt"  # Optional: Custom CA certificate

# Authentication caching
AUTH_CACHE_TTL_SECONDS = "300"  # 5 minutes

# Service account token (for local development)
OPENSHIFT_SERVICE_ACCOUNT_TOKEN = "$(oc whoami -t)"  # User token for local dev

# OAuth configuration (Phase 3)
OAUTH_CLIENT_ID = "proms-mcp-client"
OAUTH_CLIENT_SECRET_PATH = "/etc/oauth/client-secret"
OAUTH_REDIRECT_URI = "https://proms-mcp.apps.cluster.example.com/oauth/callback"
```

### Client Configuration Examples

**No Auth (Development)**:
```json
{
  "mcpServers": {
    "proms-mcp-dev": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

**Active Mode - Bearer Token (Production)**:
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

**Active Mode - OAuth (Phase 3)**:
```json
{
  "mcpServers": {
    "proms-mcp": {
      "url": "https://proms-mcp.apps.cluster.example.com/sse",
      "oauth": {
        "provider": "openshift",
        "scopes": ["user:info"]
      }
    }
  }
}
```

## File Structure

```
proms_mcp/
├── auth/
│   ├── __init__.py          # AuthMode enum, base classes
│   ├── backends.py          # NoAuthBackend, base AuthBackend
│   ├── openshift.py         # OpenShiftClient, BearerTokenBackend
│   ├── oauth.py             # OAuthBackend, OAuth flow handling
│   ├── active.py            # ActiveAuthBackend, unified authentication
│   ├── middleware.py        # FastMCP middleware integration
│   ├── models.py            # User models, authentication result types
│   └── cache.py             # Token validation caching
├── server.py                # Updated with auth middleware
└── config.py                # Updated with auth configuration
```

## Implementation Details

### Phase 1: No-Auth Implementation

**File: `proms_mcp/auth/__init__.py`**
```python
from enum import Enum
from typing import Protocol
from dataclasses import dataclass

class AuthMode(Enum):
    NONE = "none"
    ACTIVE = "active"

@dataclass
class User:
    username: str
    uid: str
    groups: list[str]
    auth_method: str

class AuthBackend(Protocol):
    async def authenticate(self, request) -> User | None:
        ...
```

**File: `proms_mcp/auth/backends.py`**
```python
from .models import User

class NoAuthBackend:
    """No authentication - for development only."""
    
    async def authenticate(self, request) -> User:
        return User(
            username="dev-user",
            uid="dev-user-id",
            groups=["developers"],
            auth_method="none"
        )
```

### Phase 2: Bearer Token Implementation

**File: `proms_mcp/auth/openshift.py`**
```python
import httpx
from typing import Optional
from .models import User
from .cache import TokenCache

class OpenShiftClient:
    def __init__(self, api_url: str, service_account_token_path: str):
        self.api_url = api_url.rstrip('/')
        self.service_account_token_path = service_account_token_path
        self.cache = TokenCache(ttl_seconds=300)
    
    async def validate_token(self, token: str) -> Optional[User]:
        # Check cache first
        cached_user = self.cache.get(token)
        if cached_user:
            return cached_user
        
        # Validate against OpenShift API
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.api_url}/apis/user.openshift.io/v1/users/~",
                    headers=headers
                )
                
                if response.status_code == 200:
                    user_info = response.json()
                    user = User(
                        username=user_info["metadata"]["name"],
                        uid=user_info["metadata"]["uid"],
                        groups=user_info.get("groups", []),
                        auth_method="active"
                    )
                    
                    # Cache the result
                    self.cache.set(token, user)
                    return user
                    
        except Exception as e:
            # Log error but don't raise
            pass
        
        return None

class BearerTokenBackend:
    def __init__(self, openshift_client: OpenShiftClient):
        self.openshift_client = openshift_client
    
    async def authenticate(self, request) -> Optional[User]:
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ", 1)[1]
        return await self.openshift_client.validate_token(token)
```

### Middleware Integration

**File: `proms_mcp/auth/middleware.py`**
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .backends import AuthBackend

class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_backend: AuthBackend):
        super().__init__(app)
        self.auth_backend = auth_backend
    
    async def dispatch(self, request, call_next):
        # Skip authentication for health checks
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)
        
        # Authenticate request
        user = await self.auth_backend.authenticate(request)
        
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"error": "Authentication required"}
            )
        
        # Add user to request state
        request.state.user = user
        
        return await call_next(request)
```

## Testing Strategy

### Unit Tests Structure

```python
# tests/auth/test_backends.py
import pytest
from proms_mcp.auth.backends import NoAuthBackend
from proms_mcp.auth.openshift import BearerTokenBackend

@pytest.mark.asyncio
async def test_no_auth_backend():
    backend = NoAuthBackend()
    user = await backend.authenticate(None)
    assert user.username == "dev-user"
    assert "developers" in user.groups

@pytest.mark.asyncio
async def test_bearer_token_valid():
    # Mock OpenShift API response
    backend = BearerTokenBackend(mock_openshift_client)
    request = MockRequest(headers={"Authorization": "Bearer valid-token"})
    
    user = await backend.authenticate(request)
    assert user is not None
    assert user.auth_method == "active"

@pytest.mark.asyncio
async def test_bearer_token_invalid():
    backend = BearerTokenBackend(mock_openshift_client)
    request = MockRequest(headers={"Authorization": "Bearer invalid-token"})
    
    user = await backend.authenticate(request)
    assert user is None
```

## Security Considerations

### Token Security
- All tokens transmitted over HTTPS only
- No token persistence in server memory beyond cache TTL
- Cache keys are hashed to prevent token leakage in logs
- Proper error handling to prevent information disclosure

### Rate Limiting
- Authentication attempts: 10 per minute per IP
- Token validation caching reduces OpenShift API load
- Circuit breaker pattern for OpenShift API failures

### Audit Logging
```python
# Log all authentication attempts
logger.info(
    "Authentication attempt",
    auth_method="active",
    client_ip=request.client.host,
    user_agent=request.headers.get("user-agent"),
    status="success" if user else "failure",
    username=user.username if user else None
)
```

## Deployment Configuration

### OpenShift Template Updates

Add authentication parameters to `openshift/deploy.yaml`:

```yaml
parameters:
# ... existing parameters ...
- name: AUTH_MODE
  description: "Authentication mode (none, active)"
  value: "active"
- name: OPENSHIFT_API_URL
  description: "OpenShift API server URL"
  required: true
- name: AUTH_CACHE_TTL_SECONDS
  description: "Authentication cache TTL in seconds"
  value: "300"

# In deployment spec:
env:
- name: AUTH_MODE
  value: "${AUTH_MODE}"
- name: OPENSHIFT_API_URL
  value: "${OPENSHIFT_API_URL}"
- name: AUTH_CACHE_TTL_SECONDS
  value: "${AUTH_CACHE_TTL_SECONDS}"
```

### Service Account Configuration

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: proms-mcp-server
  namespace: your-namespace

---
# Recommended: Use system:auth-delegator for token validation
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: proms-mcp-auth-delegator
subjects:
- kind: ServiceAccount
  name: proms-mcp-server
  namespace: your-namespace
roleRef:
  kind: ClusterRole
  name: system:auth-delegator
  apiGroup: rbac.authorization.k8s.io

---
# Optional: Namespace-scoped permissions for local resources
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: your-namespace
  name: proms-mcp-local
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: proms-mcp-local
  namespace: your-namespace
subjects:
- kind: ServiceAccount
  name: proms-mcp-server
  namespace: your-namespace
roleRef:
  kind: Role
  name: proms-mcp-local
  apiGroup: rbac.authorization.k8s.io
```

## Development Workflow

### Local Development Setup

#### Option 1: No Authentication (Development Only)
```bash
# Explicitly disable authentication for development
export AUTH_MODE=none
uv run python -m proms_mcp

# Test with Cursor - no headers needed
# .cursor/mcp.json:
{
  "mcpServers": {
    "proms-mcp-dev": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

#### Option 2: Active Authentication (Default - Recommended)
```bash
# Prerequisites: oc CLI installed and logged into OpenShift cluster
oc login https://api.your-cluster.com:6443

# Set up environment (default SSL verification)
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.your-cluster.com:6443
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t)

# Run server
uv run python -m proms_mcp

# Test with Cursor - add token header
# .cursor/mcp.json:
{
  "mcpServers": {
    "proms-mcp": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${OPENSHIFT_TOKEN}"
      }
    }
  }
}
```

#### Option 2a: Active Authentication with SSL Verification Disabled (Development)
```bash
# For development with self-signed certificates
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.your-cluster.com:6443
export OPENSHIFT_SSL_VERIFY=false  # INSECURE - development only
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t)

# Run server
uv run python -m proms_mcp
```

#### Option 2b: Active Authentication with Custom CA Certificate
```bash
# For clusters with custom CA certificates
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://api.your-cluster.com:6443
export OPENSHIFT_CA_CERT_PATH=/path/to/custom-ca.crt
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t)

# Extract CA certificate if needed
kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > custom-ca.crt

# Run server
uv run python -m proms_mcp
```

#### Option 2c: Active Authentication for In-Pod Testing
```bash
# Simulate in-pod environment
export AUTH_MODE=active
export OPENSHIFT_API_URL=https://kubernetes.default.svc:443
export OPENSHIFT_SERVICE_ACCOUNT_TOKEN_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token
export OPENSHIFT_CA_CERT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

# Note: These files need to be available locally for testing
# In actual pod deployment, they're automatically mounted
uv run python -m proms_mcp
```

#### Option 3: OAuth Testing (Advanced)
```bash
# Prerequisites: OAuth client registered in OpenShift
# Create OAuth client:
oc create -f - <<EOF
apiVersion: oauth.openshift.io/v1
kind: OAuthClient
metadata:
  name: proms-mcp-local
redirectURIs:
- "http://localhost:8000/oauth/callback"
grantMethod: auto
EOF

# Set up environment
export AUTH_MODE=active
export OAUTH_CLIENT_ID=proms-mcp-local
export OPENSHIFT_API_URL=https://api.your-cluster.com:6443
export OAUTH_REDIRECT_URI=http://localhost:8000/oauth/callback

# Run server
uv run python -m proms_mcp

# Test OAuth flow:
# 1. Navigate to: http://localhost:8000/oauth/authorize
# 2. Complete OpenShift login in browser
# 3. Get redirected back to localhost
# 4. Use OAuth token for MCP calls
```

### Local Testing Commands

#### Authentication Testing
```bash
# Test no-auth mode
curl http://localhost:8000/mcp/list_datasources

# Test bearer token (valid)
curl -H "Authorization: Bearer $(oc whoami -t)" \
     http://localhost:8000/mcp/list_datasources

# Test bearer token (invalid - should fail)
curl -H "Authorization: Bearer invalid-token" \
     http://localhost:8000/mcp/list_datasources

# Test missing auth (should fail when auth enabled)
curl http://localhost:8000/mcp/list_datasources
```

#### SSL Configuration Testing
```bash
# Test with default SSL verification (should work with trusted certs)
AUTH_MODE=active OPENSHIFT_API_URL=https://api.cluster.example.com:6443 \
  OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t) \
  uv run python -m proms_mcp

# Test with SSL verification disabled (development only)
AUTH_MODE=active OPENSHIFT_API_URL=https://api.cluster.example.com:6443 \
  OPENSHIFT_SSL_VERIFY=false \
  OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t) \
  uv run python -m proms_mcp

# Test with custom CA certificate
AUTH_MODE=active OPENSHIFT_API_URL=https://api.cluster.example.com:6443 \
  OPENSHIFT_CA_CERT_PATH=/path/to/custom-ca.crt \
  OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$(oc whoami -t) \
  uv run python -m proms_mcp

# Test internal API (for in-pod simulation)
AUTH_MODE=active OPENSHIFT_API_URL=https://kubernetes.default.svc:443 \
  OPENSHIFT_SERVICE_ACCOUNT_TOKEN_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token \
  OPENSHIFT_CA_CERT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt \
  uv run python -m proms_mcp
```

#### Token Information
```bash
# Check your current OpenShift token
oc whoami -t

# Check token expiration (tokens typically last 24 hours)
oc whoami --show-token-duration

# Check your user info (what the server will see)
oc whoami
oc whoami --show-groups
```

### Development Recommendations

1. **Secure by Default**: The server defaults to `AUTH_MODE=active` for security
2. **Development Override**: Explicitly set `AUTH_MODE=none` for local development when needed
3. **Active Mode Testing**: This is now the default - set up OpenShift authentication for full testing
4. **OAuth Testing**: Only test locally if you need to debug OAuth flows; otherwise test in dev environment
5. **Token Refresh**: Remember to refresh your OpenShift token (`oc login`) when it expires

### Makefile Integration

Add these commands to your Makefile for easier testing:

```makefile
# Authentication testing targets
.PHONY: run-no-auth run-active-auth run-active-auth-no-ssl run-active-auth-custom-ca run-active-auth-internal test-auth test-ssl-configs

run-no-auth:
	@echo "Starting server with no authentication (development only)..."
	AUTH_MODE=none uv run python -m proms_mcp

run-active-auth:
	@echo "Starting server with active authentication (default SSL verification)..."
	@echo "Requires: oc login and OPENSHIFT_API_URL environment variable"
	AUTH_MODE=active OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$$(oc whoami -t) OPENSHIFT_API_URL=https://api.cluster.example.com:6443 uv run python -m proms_mcp

run-active-auth-no-ssl:
	@echo "Starting server with active authentication (SSL verification disabled - INSECURE)..."
	@echo "Requires: oc login and OPENSHIFT_API_URL environment variable"
	AUTH_MODE=active OPENSHIFT_SSL_VERIFY=false OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$$(oc whoami -t) OPENSHIFT_API_URL=https://api.cluster.example.com:6443 uv run python -m proms_mcp

run-active-auth-custom-ca:
	@echo "Starting server with active authentication (custom CA certificate)..."
	@echo "Requires: oc login, OPENSHIFT_API_URL, and custom-ca.crt file"
	AUTH_MODE=active OPENSHIFT_CA_CERT_PATH=./custom-ca.crt OPENSHIFT_SERVICE_ACCOUNT_TOKEN=$$(oc whoami -t) OPENSHIFT_API_URL=https://api.cluster.example.com:6443 uv run python -m proms_mcp

run-active-auth-internal:
	@echo "Starting server with active authentication (internal Kubernetes API)..."
	@echo "Requires: Service account token and CA cert files in standard locations"
	AUTH_MODE=active OPENSHIFT_API_URL=https://kubernetes.default.svc:443 OPENSHIFT_SERVICE_ACCOUNT_TOKEN_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token OPENSHIFT_CA_CERT_PATH=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt uv run python -m proms_mcp

test-auth:
	@echo "Testing authentication..."
	@echo "No auth test:"
	curl -s http://localhost:8000/health || echo "Server not running"
	@echo "Bearer token test (if server running with auth):"
	curl -s -H "Authorization: Bearer $$(oc whoami -t)" http://localhost:8000/health || echo "Auth test failed"

test-ssl-configs:
	@echo "Testing SSL configuration detection..."
	@echo "Default SSL verification:"
	@AUTH_MODE=active OPENSHIFT_API_URL=https://api.cluster.example.com:6443 python -c "from proms_mcp.auth.openshift import OpenShiftClient; client = OpenShiftClient('https://api.cluster.example.com:6443'); print('SSL Config:', client._get_ssl_verify_config())"
	@echo "SSL verification disabled:"
	@OPENSHIFT_SSL_VERIFY=false AUTH_MODE=active OPENSHIFT_API_URL=https://api.cluster.example.com:6443 python -c "from proms_mcp.auth.openshift import OpenShiftClient; client = OpenShiftClient('https://api.cluster.example.com:6443'); print('SSL Config:', client._get_ssl_verify_config())"

extract-ca-cert:
	@echo "Extracting CA certificate from current kubeconfig context..."
	kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > custom-ca.crt
	@echo "CA certificate saved as custom-ca.crt"
```

This phased approach allows for incremental implementation while maintaining the lean design principles of the MCP server. 
