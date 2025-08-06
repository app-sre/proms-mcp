# TokenReview API Implementation Plan

## Executive Summary

This plan outlines migrating from our custom OpenShift client to using Kubernetes native TokenReview and SelfSubjectAccessReview APIs for authentication and authorization. This approach aligns with FastMCP 2.11+ patterns and significantly simplifies our authentication architecture.

## Current State Analysis

### Current Implementation

- **Custom OpenShiftClient**: Complex wrapper around OpenShift API
- **Token Validation**: Custom logic for JWT and opaque token validation
- **Authorization**: Group-based mapping to scopes
- **Caching**: Custom token cache implementation
- **Code Complexity**: ~400 lines across multiple files

### Pain Points

- **Maintenance Burden**: Custom client requires ongoing maintenance
- **Complexity**: Multiple validation paths for different token types
- **Performance**: Multiple API calls for validation
- **Security**: Custom validation logic vs. proven Kubernetes APIs
- **Testing**: Complex mocking for custom client behavior

## Proposed Solution: Native Kubernetes APIs

### Architecture Overview

```
┌─────────────────┐    ┌──────────────────────┐    ┌─────────────────┐
│   MCP Client    │───▶│   FastMCP Server     │───▶│  OpenShift API  │
│                 │    │                      │    │                 │
│ Bearer Token    │    │ OpenShiftTokenVerifier│    │ TokenReview     │
└─────────────────┘    │                      │    │ SelfSubject*    │
                       └──────────────────────┘    └─────────────────┘
```

### Core Components

#### 1. TokenReview API for Authentication

- **Purpose**: Validate bearer token authenticity
- **Endpoint**: `/apis/authentication.k8s.io/v1/tokenreviews`
- **Input**: Bearer token from request
- **Output**: User identity (username, uid, groups)

#### 2. SelfSubjectAccessReview API for Authorization

- **Purpose**: Check specific RBAC permissions
- **Endpoint**: `/apis/authorization.k8s.io/v1/selfsubjectaccessreviews`
- **Input**: User token + resource/verb to check
- **Output**: Boolean permission result

#### 3. Simplified Token Verifier

- **Role**: FastMCP TokenVerifier implementation
- **Responsibilities**: Coordinate API calls, map to FastMCP scopes
- **Benefits**: Leverage proven Kubernetes authentication

## Implementation Plan

### Phase 1: Create New TokenReview-Based Verifier

#### File: `proms_mcp/auth/tokenreview_auth.py`

```python
"""FastMCP TokenVerifier using Kubernetes TokenReview API."""

import time
from typing import TYPE_CHECKING

import httpx
import structlog
from fastmcp.server.auth.provider import AccessToken
from fastmcp.server.auth.verifier import TokenVerifier

if TYPE_CHECKING:
    from . import User

logger = structlog.get_logger()


class TokenReviewVerifier(TokenVerifier):
    """FastMCP TokenVerifier using Kubernetes TokenReview API.
    
    This implementation uses the standard Kubernetes TokenReview API
    to validate bearer tokens and SelfSubjectAccessReview API to check
    RBAC permissions. This approach is simpler and more reliable than
    custom token validation logic.
    """
    
    def __init__(
        self,
        api_url: str,
        required_scopes: list[str] | None = None,
    ):
        """Initialize the TokenReview verifier.
        
        Args:
            api_url: OpenShift/Kubernetes API server URL
            required_scopes: Base scopes required for access
        """
        super().__init__(
            resource_server_url=None,  # No OAuth2 metadata generation needed
            required_scopes=required_scopes or ["read:data"],
        )
        self.api_url = api_url.rstrip("/")
        
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using Kubernetes TokenReview API."""
        try:
            # Validate token and get user identity
            user = await self._validate_token_identity(token)
            if not user:
                logger.debug("Token validation failed")
                return None
                
            logger.info("Token validated successfully", username=user.username)
            
            # For now, all authenticated users get full access
            return AccessToken(
                token=token,
                client_id=user.username,
                scopes=["read:data", "write:data"],  # All authenticated users get full access
                expires_at=int(time.time()) + 3600,  # 1 hour
                resource="proms-mcp-server",
            )
            
        except Exception as e:
            logger.error("Token verification failed", error=str(e))
            return None
    
    async def _validate_token_identity(self, token: str) -> "User | None":
        """Validate token using TokenReview API."""
        payload = {
            "kind": "TokenReview",
            "apiVersion": "authentication.k8s.io/v1",
            "spec": {"token": token}
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{self.api_url}/apis/authentication.k8s.io/v1/tokenreviews",
                    json=payload,
                    # Note: No Authorization header - TokenReview validates the token in spec.token
                )
                
                if response.status_code != 200:
                    logger.debug(
                        "TokenReview request failed",
                        status_code=response.status_code,
                        response=response.text[:200]
                    )
                    return None
                
                result = response.json()
                status = result.get("status", {})
                
                if not status.get("authenticated", False):
                    logger.debug("Token not authenticated by TokenReview")
                    return None
                
                user_info = status.get("user", {})
                return User(
                    username=user_info.get("username", ""),
                    uid=user_info.get("uid", ""),
                    groups=user_info.get("groups", []),
                    auth_method="tokenreview"
                )
                
            except httpx.TimeoutException:
                logger.error("TokenReview request timed out")
                return None
            except Exception as e:
                logger.error("TokenReview request failed", error=str(e))
                return None


### Phase 2: Update Server Integration

#### Modify `proms_mcp/server.py`

```python
# Replace OpenShiftClient import with TokenReviewVerifier
from proms_mcp.auth import AuthMode
from proms_mcp.auth.tokenreview_auth import TokenReviewVerifier

def initialize_server() -> None:
    """Initialize the FastMCP server with authentication."""
    global app
    
    auth_mode = AuthMode(os.getenv("AUTH_MODE", "none"))
    
    if auth_mode == AuthMode.ACTIVE:
        # Get OpenShift API URL from environment
        api_url = os.getenv("OPENSHIFT_API_URL")
        if not api_url:
            raise ValueError("OPENSHIFT_API_URL required when AUTH_MODE=active")
            
        # Create TokenReview-based verifier
        auth_provider = TokenReviewVerifier(
            api_url=api_url,
            required_scopes=["read:data"]
        )
        
        app = FastMCP(
            name="Prometheus MCP Server",
            auth=auth_provider
        )
    else:
        app = FastMCP(name="Prometheus MCP Server")
    
    _register_tools()
```

### Phase 3: Clean Up Legacy Code

#### Files to Remove

- `proms_mcp/auth/openshift.py` (OpenShiftClient class)
- `proms_mcp/auth/cache.py` (custom token caching)
- Related test files

#### Files to Update

- `proms_mcp/auth/__init__.py` - Update exports
- `README.md` - Update authentication documentation
- `TESTING.md` - Update test examples

### Phase 4: Update Configuration

#### Environment Variables

- **Keep**: `AUTH_MODE`, `OPENSHIFT_API_URL`
- **Remove**: Custom cache settings, client-specific configs
- **Note**: All parameters come from environment variables, no changes to datasources.yaml format

#### Environment Variables Configuration

```bash
# Required
AUTH_MODE=active
OPENSHIFT_API_URL=https://api.cluster.example.com:6443

# Optional - auto-detected if not provided
HOST=0.0.0.0
PORT=8000
```

## Simplified Authentication Approach

### Key Principle: No OAuth2 Complexity

This implementation uses **simple bearer token validation** against Kubernetes APIs:

1. **Client Authentication**: Clients send `Authorization: Bearer <token>` headers
2. **Token Validation**: We validate tokens using Kubernetes TokenReview API
3. **Authorization**: All authenticated users get full access (for now)
4. **No OAuth2**: No complex OAuth2 flows, discovery metadata, or redirect handling

### FastMCP Integration

We use FastMCP's `TokenVerifier` base class but configure it for simple token validation:

- `resource_server_url=None` - No OAuth2 metadata generation
- `required_scopes` - Simple scope-based authorization
- Direct token validation without OAuth2 complexity

## Reasoning Behind Choices

### Why TokenReview API?

1. **Proven Security**: Kubernetes-native token validation
2. **Simplicity**: Single API call vs. complex custom logic
3. **Reliability**: Handles all token types (JWT, opaque) uniformly
4. **Performance**: Optimized by Kubernetes team
5. **Maintenance**: No custom validation logic to maintain

### Why Simple Authorization?

1. **Simplicity**: All authenticated users get access - no complex permission logic
2. **Fast Implementation**: No additional API calls needed for authorization
3. **Clear Security Model**: Token validation is the only security gate
4. **Easy to Extend**: Can add RBAC checks later without changing the authentication flow
5. **Predictable Behavior**: If you can authenticate, you can use the service

### Why Simplify Architecture?

1. **Reduced Complexity**: ~400 lines → ~150 lines
2. **Better Testing**: Mock HTTP calls vs. complex client behavior
3. **Easier Debugging**: Standard API responses vs. custom logic
4. **Future-Proof**: Kubernetes APIs evolve, our custom code doesn't
5. **Performance**: Fewer moving parts, better caching opportunities

### Why Preserve FastMCP Integration?

1. **Consistency**: Follows FastMCP 2.11+ patterns
2. **Compatibility**: Works with existing FastMCP tooling
3. **Standards**: Uses OAuth-style scopes for authorization (but NOT OAuth2 flows)
4. **Flexibility**: Easy to migrate to other auth providers later

## Migration Strategy

### Phase 1: Implementation (Week 1)

- [ ] Create `TokenReviewVerifier` class
- [ ] Add comprehensive unit tests
- [ ] Update server integration
- [ ] Test with existing tokens

### Phase 2: Integration Testing (Week 1)

- [ ] Test with real OpenShift cluster
- [ ] Verify all token types work
- [ ] Performance testing
- [ ] Error handling validation

### Phase 3: Cleanup (Week 2)

- [ ] Remove legacy OpenShift client
- [ ] Update documentation
- [ ] Clean up test files
- [ ] Update deployment configs

### Phase 4: RBAC Enhancement (Future)

- [ ] Define specific RBAC permission mappings
- [ ] Implement tool-level authorization
- [ ] Add permission caching if needed
- [ ] Document RBAC setup guide

## Benefits Summary

### Immediate Benefits

- **Reduced Complexity**: 60% less authentication code
- **Better Reliability**: Proven Kubernetes APIs
- **Easier Testing**: Standard HTTP mocking
- **Improved Performance**: Fewer API calls

### Long-term Benefits

- **Lower Maintenance**: No custom client to maintain
- **Better Security**: Kubernetes-native validation
- **Enhanced Flexibility**: Easy RBAC permission mapping
- **Future-Proof**: Aligns with Kubernetes standards

### Operational Benefits

- **Simplified Deployment**: Fewer configuration options
- **Better Debugging**: Standard API error messages
- **Easier Monitoring**: Standard HTTP metrics
- **Reduced Attack Surface**: Less custom code

## Risk Mitigation

### Potential Risks

1. **API Availability**: OpenShift API must be reachable
2. **Performance**: Additional HTTP calls for permission checks
3. **Token Expiration**: Need to handle token refresh properly

### Mitigation Strategies

1. **Timeouts**: Reasonable timeouts for all API calls
2. **Caching**: Cache permission results if needed
3. **Graceful Degradation**: Fallback behavior for API failures
4. **Monitoring**: Track API call success rates

## Success Criteria

### Functional Requirements

- [ ] All existing functionality preserved
- [ ] Authentication works with all token types
- [ ] Performance equal or better than current implementation
- [ ] Zero security regressions

### Code Quality Requirements (per SPECS.md)

- [ ] **Linting and Formatting**: All `make lint` and `make format` checks pass
- [ ] **Type Checking**: All `mypy` type checking passes without errors
- [ ] **Test Coverage**: Maintain >95% test coverage as specified in SPECS.md
- [ ] **Test Integrity**: All tests pass without `pytest.mark.skip` decorators
- [ ] **No Test Removal**: Tests only removed for features that were actually deleted
- [ ] **Quality Gates**: `make format && make lint && make test` passes completely

### Documentation and Integration

- [ ] Documentation updated to reflect new architecture
- [ ] FastMCP 2.11+ integration maintained

## Future Enhancements

### Phase 5: RBAC-Based Authorization (Future)

DO NOT IMPLEMENT THIS FOR NOW!

Once the basic TokenReview implementation is working, we may add fine-grained authorization using **SelfSubjectAccessReview API**:

#### **Implementation Approach**

- Add `_determine_user_scopes()` method to check specific RBAC permissions
- Use `SelfSubjectAccessReview` API to validate user permissions for specific resources
- Map RBAC permissions to FastMCP scopes (e.g., `read:metrics`, `write:config`, `admin:all`)

#### **Example Permission Checks**

```python
# Check if user can read prometheus metrics
if await self._can_access_resource(token, "get", "metrics", "monitoring.coreos.com"):
    scopes.append("read:metrics")

# Check if user can create prometheus rules  
if await self._can_access_resource(token, "create", "prometheusrules", "monitoring.coreos.com"):
    scopes.append("write:config")

# Check for cluster admin permissions
if await self._can_access_resource(token, "get", "nodes", ""):
    scopes.append("admin:all")
```

#### **Benefits of Future RBAC Integration**

- **Fine-grained Control**: Different users get different access levels
- **RBAC Integration**: Leverages existing Kubernetes RBAC policies  
- **Tool-specific Permissions**: Can restrict access to specific MCP tools
- **Namespace Scoping**: Can limit access to specific namespaces
- **Audit Integration**: All permission checks logged by Kubernetes

### Phase 6: Multi-Cluster Support (Future)

- Support for multiple OpenShift clusters
- Cross-cluster token validation
- Federated authentication scenarios

This implementation plan provides a clear path to modernize our authentication while maintaining security and reliability. The TokenReview approach aligns with FastMCP best practices and significantly simplifies our codebase.
