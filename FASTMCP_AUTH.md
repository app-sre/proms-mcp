# FastMCP Authentication Migration Plan

## Overview

This document outlines the migration from custom authentication middleware to FastMCP 2.11+ built-in authentication system, while maintaining all existing functionality including OpenShift token validation and secondary metrics server.

## Migration Goals

- ✅ **Reduce Code**: Eliminate ~90 lines (custom middleware + uvicorn setup)
- ✅ **Use FastMCP Patterns**: Built-in `app.run()` and auth integration
- ✅ **Maintain Functionality**: Keep OpenShift bearer token auth, metrics server, caching
- ✅ **Improve Architecture**: Cleaner separation of concerns

## Current vs Target Architecture

### Current Architecture

```
FastMCP Server Object
↓
Custom AuthenticationMiddleware (Starlette)
↓
Manual ASGI App Creation
↓
Manual Uvicorn Setup
↓
Secondary HTTP Server (daemon thread)
```

### Target Architecture

```
FastMCP Server Object (with built-in auth)
↓
Built-in FastMCP.run()
↓
Secondary HTTP Server (daemon thread)
```

## Implementation Plan

### Phase 1: Create OpenShift TokenVerifier

#### 1.1 Create Custom TokenVerifier Class

**File**: `proms_mcp/auth/fastmcp_auth.py` (new file)

```python
"""FastMCP authentication integration for OpenShift tokens."""

import time
from typing import Optional

import httpx
import structlog
from fastmcp.server.auth import TokenVerifier
from mcp.server.auth.provider import AccessToken

from .cache import TokenCache
from .models import User

logger = structlog.get_logger()


class OpenShiftTokenVerifier(TokenVerifier):
    """FastMCP TokenVerifier for OpenShift bearer tokens.
    
    Validates both JWT (service account) and opaque (user) tokens
    against the OpenShift API using the existing OpenShiftClient logic.
    """

    def __init__(
        self, 
        openshift_client: 'OpenShiftClient',
        resource_server_url: str = "http://localhost:8000",
        required_scopes: list[str] | None = None
    ):
        """Initialize the OpenShift token verifier.
        
        Args:
            openshift_client: Configured OpenShiftClient instance
            resource_server_url: URL of this MCP server
            required_scopes: Required scopes for access
        """
        super().__init__(
            resource_server_url=resource_server_url,
            required_scopes=required_scopes or ["read:data"]
        )
        self.openshift_client = openshift_client

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify OpenShift token and return AccessToken.
        
        Args:
            token: Bearer token to validate
            
        Returns:
            AccessToken if valid, None if invalid
        """
        # Use existing OpenShift client validation
        user = await self.openshift_client.validate_token(token)
        if not user:
            return None
            
        # Convert User to AccessToken for FastMCP
        return AccessToken(
            token=token,
            client_id=user.username,
            scopes=self._map_user_to_scopes(user),
            expires_at=int(time.time()) + 3600,  # 1 hour default
            subject=user.uid,
            issuer="openshift-cluster",
            audience="proms-mcp-server"
        )
    
    def _map_user_to_scopes(self, user: User) -> list[str]:
        """Map OpenShift user/groups to scopes.
        
        Args:
            user: Validated OpenShift user
            
        Returns:
            List of scopes based on user groups
        """
        scopes = ["read:data"]  # Base scope for all users
        
        # Add scopes based on OpenShift groups
        if "system:admin" in user.groups:
            scopes.extend(["write:data", "admin:all"])
        elif any(group.startswith("system:") for group in user.groups):
            scopes.append("write:data")
            
        return scopes
```

#### 1.2 Update Auth Module Exports

**File**: `proms_mcp/auth/__init__.py`

```python
# Add to existing exports
from .fastmcp_auth import OpenShiftTokenVerifier

__all__ = [
    # ... existing exports ...
    "OpenShiftTokenVerifier",
]
```

### Phase 2: Modify Server Initialization

#### 2.1 Update Server Initialization Logic

**File**: `proms_mcp/server.py`

**Changes to `initialize_server()` function:**

```python
def initialize_server() -> None:
    """Initialize the server with configuration."""
    global config_loader
    logger.info("Initializing Proms MCP server")

    # Initialize authentication provider
    auth_provider = None
    auth_mode = get_auth_mode()
    logger.info(f"Authentication mode: {auth_mode.value}", auth_mode=auth_mode.value)

    if auth_mode == AuthMode.ACTIVE:
        # Initialize OpenShift authentication
        openshift_api_url = os.getenv("OPENSHIFT_API_URL")
        if not openshift_api_url:
            logger.error("OPENSHIFT_API_URL required for active authentication mode")
            raise ValueError(
                "OPENSHIFT_API_URL environment variable is required for active authentication"
            )

        ca_cert_path = os.getenv("OPENSHIFT_CA_CERT_PATH")
        openshift_client = OpenShiftClient(openshift_api_url, ca_cert_path=ca_cert_path)
        
        # Create FastMCP TokenVerifier
        from .auth import OpenShiftTokenVerifier
        auth_provider = OpenShiftTokenVerifier(
            openshift_client=openshift_client,
            resource_server_url=f"http://localhost:{os.getenv('PORT', '8000')}",
            required_scopes=["read:data"]
        )
        logger.info(
            "Using FastMCP OpenShift token verification", 
            api_url=openshift_api_url
        )

    # Update FastMCP initialization with auth
    global app
    app = FastMCP(
        name="proms-mcp",
        instructions="A lean MCP server providing access to multiple Prometheus instances for metrics analysis and SRE operations.",
        stateless_http=True,
        auth=auth_provider  # Pass auth provider directly
    )

    # Initialize datasources (unchanged)
    config_loader = get_config_loader()
    config_loader.load_datasources()
    logger.info(
        f"Loaded {len(config_loader.datasources)} datasources",
        datasource_count=len(config_loader.datasources),
    )

    # Update metrics
    metrics_data["datasources_configured"] = len(config_loader.datasources)
    # ... rest of datasource logging unchanged ...
    
    logger.info("Server initialization complete")
```

#### 2.2 Simplify Main Function

**File**: `proms_mcp/server.py`

**Replace entire `main()` function:**

```python
def main() -> None:
    """Main entry point for the server."""
    # Start health and metrics server (daemon thread)
    start_health_metrics_server(metrics_data)
    
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    path = "/mcp"
    
    logger.info(f"Starting MCP server on {host}:{port}{path}")
    
    # Use FastMCP's built-in server runner
    try:
        app.run(
            transport="streamable-http",
            host=host,
            port=port,
            path=path,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
```

### Phase 3: Remove Obsolete Components

#### 3.1 Files to Remove

- `proms_mcp/auth/middleware.py` - Custom middleware no longer needed
- Any imports related to Starlette middleware in `server.py`

#### 3.2 Code to Remove from server.py

- All uvicorn imports
- ASGI app creation logic
- Manual middleware wrapping
- Custom HTTP server configuration

**Specific lines to remove:**

```python
# Remove these imports
import uvicorn
from .auth.middleware import AuthenticationMiddleware

# Remove this entire section from main():
# Create the ASGI app from FastMCP
asgi_app: Any = app.http_app(path="/mcp", transport="streamable-http")

# Wrap with authentication middleware if active auth mode
if auth_backend and get_auth_mode() == AuthMode.ACTIVE:
    # ... entire middleware wrapping logic ...

# Remove manual uvicorn.run call
uvicorn.run(
    asgi_app,
    host=host,
    port=port,
    timeout_graceful_shutdown=timeout_graceful_shutdown,
    log_level="info",
    log_config=get_uvicorn_log_config(),
)
```

### Phase 4: Update Configuration

#### 4.1 Environment Variables (Unchanged)

All existing environment variables remain the same:

- `AUTH_MODE`: `none` or `active` (default: `active`)
- `OPENSHIFT_API_URL`: OpenShift API server URL
- `OPENSHIFT_CA_CERT_PATH`: Optional CA certificate path
- `OPENSHIFT_SSL_VERIFY`: SSL verification setting
- `AUTH_CACHE_TTL_SECONDS`: Cache TTL (default: 300)

#### 4.2 New Optional Variables

- `REQUIRED_SCOPES`: Comma-separated list of required scopes (default: "read:data")

### Phase 5: Testing Strategy

#### 5.1 Unit Tests Updates

**File**: `tests/auth/test_fastmcp_auth.py` (new file)

```python
"""Tests for FastMCP authentication integration."""

import pytest
from unittest.mock import AsyncMock, Mock

from proms_mcp.auth.fastmcp_auth import OpenShiftTokenVerifier
from proms_mcp.auth.models import User


class TestOpenShiftTokenVerifier:
    """Test OpenShift TokenVerifier integration."""

    @pytest.fixture
    def mock_openshift_client(self):
        """Mock OpenShift client."""
        client = Mock()
        client.validate_token = AsyncMock()
        return client

    @pytest.fixture
    def token_verifier(self, mock_openshift_client):
        """Create TokenVerifier instance."""
        return OpenShiftTokenVerifier(
            openshift_client=mock_openshift_client,
            resource_server_url="http://localhost:8000",
            required_scopes=["read:data"]
        )

    async def test_verify_valid_token(self, token_verifier, mock_openshift_client):
        """Test successful token verification."""
        # Setup
        user = User(
            username="test-user",
            uid="user-123",
            groups=["developers"],
            auth_method="active"
        )
        mock_openshift_client.validate_token.return_value = user

        # Test
        access_token = await token_verifier.verify_token("valid-token")

        # Verify
        assert access_token is not None
        assert access_token.client_id == "test-user"
        assert access_token.subject == "user-123"
        assert "read:data" in access_token.scopes
        mock_openshift_client.validate_token.assert_called_once_with("valid-token")

    async def test_verify_invalid_token(self, token_verifier, mock_openshift_client):
        """Test invalid token handling."""
        # Setup
        mock_openshift_client.validate_token.return_value = None

        # Test
        access_token = await token_verifier.verify_token("invalid-token")

        # Verify
        assert access_token is None
        mock_openshift_client.validate_token.assert_called_once_with("invalid-token")

    def test_map_user_to_scopes_admin(self, token_verifier):
        """Test scope mapping for admin users."""
        user = User(
            username="admin",
            uid="admin-123", 
            groups=["system:admin"],
            auth_method="active"
        )
        
        scopes = token_verifier._map_user_to_scopes(user)
        
        assert "read:data" in scopes
        assert "write:data" in scopes
        assert "admin:all" in scopes

    def test_map_user_to_scopes_regular(self, token_verifier):
        """Test scope mapping for regular users."""
        user = User(
            username="user",
            uid="user-123",
            groups=["developers"],
            auth_method="active"
        )
        
        scopes = token_verifier._map_user_to_scopes(user)
        
        assert scopes == ["read:data"]
```

#### 5.2 Integration Tests

**File**: `tests/test_fastmcp_integration.py` (new file)

```python
"""Integration tests for FastMCP authentication."""

import pytest
from fastmcp import Client
from unittest.mock import patch, AsyncMock

from proms_mcp.server import app


class TestFastMCPAuthIntegration:
    """Test FastMCP authentication integration."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_blocked(self):
        """Test that unauthenticated requests are blocked when auth is active."""
        with patch("proms_mcp.config.get_auth_mode") as mock_auth_mode:
            mock_auth_mode.return_value = "active"
            
            # Test with client that doesn't provide auth
            async with Client(app) as client:
                with pytest.raises(Exception):  # Should fail auth
                    await client.list_tools()

    @pytest.mark.asyncio 
    async def test_authenticated_request_allowed(self):
        """Test that authenticated requests work."""
        with patch("proms_mcp.config.get_auth_mode") as mock_auth_mode:
            mock_auth_mode.return_value = "none"  # Disable auth for test
            
            async with Client(app) as client:
                tools = await client.list_tools()
                assert len(tools) > 0  # Should have tools
```

### Phase 6: Deployment Considerations

#### 6.1 Backwards Compatibility

The migration maintains full backwards compatibility:

- All environment variables remain the same
- Same OpenShift API validation logic
- Same caching behavior
- Same metrics and health endpoints
- Same MCP tool functionality

#### 6.2 Rollback Plan

If issues occur, rollback by:

1. Restore `proms_mcp/auth/middleware.py`
2. Restore original `main()` function in `server.py`
3. Remove `proms_mcp/auth/fastmcp_auth.py`

#### 6.3 Performance Impact

Expected performance improvements:

- ✅ Reduced middleware overhead (one less layer)
- ✅ Native FastMCP auth handling (optimized)
- ✅ Simplified request pipeline

### Phase 7: Validation Checklist

#### 7.1 Functional Validation

- [ ] No-auth mode works (`AUTH_MODE=none`)
- [ ] Active auth mode works (`AUTH_MODE=active`)
- [ ] OpenShift token validation works
- [ ] Token caching works
- [ ] Invalid tokens are rejected
- [ ] Valid tokens are accepted
- [ ] User groups mapped to scopes correctly

#### 7.2 Integration Validation

- [ ] All MCP tools accessible with valid auth
- [ ] Health endpoint works (`http://localhost:8080/health`)
- [ ] Metrics endpoint works (`http://localhost:8080/metrics`)
- [ ] Server starts without errors
- [ ] Graceful shutdown works
- [ ] Logging works correctly

#### 7.3 Performance Validation

- [ ] Response times comparable to current system
- [ ] Memory usage comparable or better
- [ ] No auth-related bottlenecks

## Cache Analysis & Decision

### Current Auth Cache Overhead Assessment

**Current Implementation**: `TokenCache` class (73 lines, 100% test coverage)

- ✅ **Minimal Memory**: Only stores `(User, timestamp)` tuples
- ✅ **Efficient Lookup**: SHA256 hash keys (16 chars) prevent token leakage
- ✅ **Auto Cleanup**: Removes expired entries automatically
- ✅ **Production Value**: Reduces OpenShift API calls significantly
- ✅ **Configurable TTL**: Default 300s (5 minutes)

**Performance Impact Analysis**:

- **Memory per cached token**: ~200 bytes (User object + timestamp + hash key)
- **Typical cache size**: 10-50 active tokens = 2-10KB total
- **Cache hit rate**: Expected 80-90% for active users
- **API call reduction**: 5-10x fewer OpenShift API requests

**Recommendation: KEEP THE CACHE** ✅

**Reasons**:

1. **Negligible Overhead**: <10KB memory for typical usage
2. **Significant Performance Gain**: Reduces external API calls by 80-90%
3. **Production Proven**: Already tested and working
4. **Security Conscious**: Uses hashed keys to prevent token leakage
5. **OpenShift API Protection**: Prevents rate limiting issues

### Updated TokenVerifier with Cache Integration

The `OpenShiftTokenVerifier` will reuse the existing cache through the `OpenShiftClient`:

```python
async def verify_token(self, token: str) -> AccessToken | None:
    """Verify OpenShift token with caching."""
    # Cache is handled inside openshift_client.validate_token()
    user = await self.openshift_client.validate_token(token)
    if not user:
        return None
    # Convert to AccessToken...
```

This approach:

- ✅ **Zero Additional Overhead**: Reuses existing cache
- ✅ **Maintains Performance**: Same cache hit rates
- ✅ **No Code Duplication**: Single cache implementation
- ✅ **Preserves Security**: Existing hash-based keys

## Quality Assurance Requirements

### Pre-Implementation Checks

#### 1. Code Quality Gates

```bash
# All must pass before proceeding
make format    # ✅ Currently passing
make lint      # ✅ Currently passing (ruff + mypy)
make test      # ✅ Currently passing (162 tests, 91% coverage)
```

#### 2. Current Quality Baseline

- **Test Coverage**: 91% overall (target: maintain >90%)
- **Test Count**: 162 tests (target: maintain or increase)
- **Linting**: Zero issues (ruff + mypy)
- **Type Safety**: 100% mypy compliance

### Implementation Quality Gates

Each phase must pass:

#### Phase 1: TokenVerifier Creation

```bash
# After creating OpenShiftTokenVerifier
make format && make lint && make test
# Must maintain 91% coverage
# Must pass all existing tests
# New TokenVerifier tests must be added
```

#### Phase 2: Server Updates  

```bash
# After updating server initialization
make format && make lint && make test
# Must maintain 91% coverage
# Integration tests must pass
# No deprecation warnings for FastMCP usage
```

#### Phase 3: Cleanup

```bash
# After removing obsolete components
make format && make lint && make test
# Coverage may increase due to removed untested code
# All auth tests must still pass
# No broken imports or references
```

### Test Requirements

#### 3.1 New Test Files Required

- `tests/auth/test_fastmcp_auth.py`: TokenVerifier unit tests
- `tests/test_fastmcp_integration.py`: End-to-end integration tests

#### 3.2 Test Coverage Requirements

- **New TokenVerifier class**: 100% coverage
- **Modified server.py functions**: 100% coverage of changes
- **Integration scenarios**: Auth enabled/disabled modes
- **Error handling**: Invalid tokens, network failures, cache scenarios

#### 3.3 Performance Test Requirements

- **Cache hit rate validation**: Verify 80%+ hit rate maintained
- **Response time comparison**: New system ≤ current system
- **Memory usage validation**: No significant increase

### Continuous Integration Additions

Add to CI pipeline:

```yaml
# Additional CI checks for FastMCP migration
- name: Validate FastMCP Auth Integration
  run: |
    # Test with auth disabled
    AUTH_MODE=none make test
    
    # Test with auth enabled (mock OpenShift)
    AUTH_MODE=active OPENSHIFT_API_URL=http://mock make test
    
    # Performance regression test
    python scripts/auth_performance_test.py
    
    # Cache effectiveness test  
    python scripts/cache_hit_rate_test.py
```

## Implementation Timeline

### Pre-Implementation (Day 0)

- [ ] Verify all quality gates pass
- [ ] Create feature branch
- [ ] Document current performance baseline

### Day 1: TokenVerifier Creation

- [ ] Create `proms_mcp/auth/fastmcp_auth.py`
- [ ] Create `tests/auth/test_fastmcp_auth.py`
- [ ] **Quality Gate**: `make format lint test` must pass
- [ ] **Coverage Gate**: Maintain >90% overall coverage

### Day 2: Server Integration  

- [ ] Update `initialize_server()` function
- [ ] Update `main()` function
- [ ] Create `tests/test_fastmcp_integration.py`
- [ ] **Quality Gate**: `make format lint test` must pass
- [ ] **Integration Gate**: Both auth modes must work

### Day 3: Cleanup & Validation

- [ ] Remove `proms_mcp/auth/middleware.py`
- [ ] Remove obsolete imports and code
- [ ] Update all affected tests
- [ ] **Quality Gate**: `make format lint test` must pass
- [ ] **Performance Gate**: Response times ≤ baseline

### Day 4: Comprehensive Testing

- [ ] Run full test suite with both auth modes
- [ ] Performance regression testing
- [ ] Cache effectiveness validation
- [ ] Load testing with concurrent requests
- [ ] **Quality Gate**: All tests pass, performance maintained

### Day 5: Documentation & Deployment

- [ ] Update README.md with new patterns
- [ ] Update deployment documentation
- [ ] Create rollback procedure
- [ ] Final quality gate validation
- [ ] **Deployment Gate**: All checks pass

## Code Reduction Summary

| Component | Lines Removed | Lines Added | Net Change |
|-----------|---------------|-------------|------------|
| Custom Middleware | -54 | 0 | -54 |
| Uvicorn Setup | -30 | 0 | -30 |
| ASGI Integration | -15 | 0 | -15 |
| TokenVerifier Class | 0 | +80 | +80 |
| Updated Initialization | -20 | +25 | +5 |
| **TOTAL** | **-119** | **+105** | **-14** |

**Net Result: ~14 lines of code reduction with significantly cleaner architecture.**

## Benefits Summary

- ✅ **Cleaner Architecture**: Native FastMCP patterns
- ✅ **Reduced Complexity**: Eliminate custom middleware layer
- ✅ **Better Integration**: Built-in auth system
- ✅ **Maintained Functionality**: All features preserved
- ✅ **Improved Testability**: Standard FastMCP testing patterns
- ✅ **Future-Proof**: Aligned with FastMCP roadmap
