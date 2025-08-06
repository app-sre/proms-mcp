Yes, you can definitely use FastMCP 2.11+'s token verification facility for OpenShift tokens! Here's how to configure it to handle both JWT and opaque tokens:

**Configuration Approach:**

Since OpenShift can use both JWT (service accounts) and opaque tokens (OAuth users), you'll need a custom `TokenVerifier` that can handle both formats:

```python
# Configuration concept - subclass TokenVerifier
class OpenShiftTokenVerifier(TokenVerifier):
    def __init__(self, k8s_api_server_url, ca_cert_path=None):
        # Store K8s API server details for token validation
        pass
    
    async def verify_token(self, token: str) -> TokenInfo:
        # 1. First try to decode as JWT (for service accounts)
        # 2. If that fails, treat as opaque token
        # 3. Validate against K8s API using TokenReview
        pass
```

**Key Configuration Elements:**

1. **Hybrid Detection**: Check if token has JWT structure (3 parts separated by dots)
2. **Service Account JWTs**: Validate signature using K8s service account public keys
3. **Opaque Tokens**: Use Kubernetes `TokenReview` API to validate against the cluster
4. **TokenReview Call**: `POST /api/v1/tokenreviews` with the token to get user/serviceaccount info

**FastMCP Integration:**

```python
# Server setup
verifier = OpenShiftTokenVerifier(
    k8s_api_server_url="https://api.your-cluster.com:6443",
    ca_cert_path="/path/to/ca.crt"  # or set verify=False for dev
)

server = Server()
server.set_token_verifier(verifier)
```

The beauty is that FastMCP's `TokenVerifier` base class handles the bearer token extraction and routing - you just implement the OpenShift-specific validation logic in `verify_token()`. The TokenReview API is perfect since it works for both token types and returns consistent user/group information for authorization decisions.

Here's the detailed implementation for both parts:

## verify_token Function Details

```python
import json
import base64
import aiohttp
import time
from typing import Optional
from fastmcp.server.auth import TokenVerifier
from mcp.server.auth.provider import AccessToken

class OpenShiftTokenVerifier(TokenVerifier):
    def __init__(self, k8s_api_server_url: str, ca_cert_path: Optional[str] = None):
        super().__init__(
            resource_server_url="http://localhost:8000",  # Your server URL
            required_scopes=["read:data"]  # Define required scopes
        )
        self.api_server = k8s_api_server_url.rstrip('/')
        self.ca_cert = ca_cert_path
        self.session = None
    
    async def _get_session(self):
        if not self.session:
            connector = aiohttp.TCPConnector(
                ssl_context=True if self.ca_cert else False
            )
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session
    
    def _is_jwt(self, token: str) -> bool:
        """Check if token has JWT structure (3 parts separated by dots)"""
        parts = token.split('.')
        return len(parts) == 3
    
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token against OpenShift/K8s API using TokenReview"""
        
        # Create TokenReview request
        token_review = {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "spec": {
                "token": token
            }
        }
        
        session = await self._get_session()
        
        try:
            # Call K8s TokenReview API
            async with session.post(
                f"{self.api_server}/api/v1/tokenreviews",
                json=token_review,
                headers={"Content-Type": "application/json"},
                ssl=self.ca_cert if self.ca_cert else False
            ) as response:
                
                if response.status != 201:
                    raise ValueError(f"TokenReview failed: {response.status}")
                
                result = await response.json()
                status = result.get("status", {})
                
                if not status.get("authenticated", False):
                    return None
                
                # Extract user info
                user_info = status.get("user", {})
                username = user_info.get("username", "unknown")
                groups = user_info.get("groups", [])
                uid = user_info.get("uid", "")
                
                # Return AccessToken object as required by FastMCP
                return AccessToken(
                    token=token,
                    client_id=username,
                    scopes=["read:data", "write:data"],  # Map from user.groups or define as needed
                    expires_at=int(time.time()) + 3600,  # OpenShift tokens don't have expiry, set reasonable default
                    subject=uid,
                    issuer="openshift-cluster",
                    audience="proms-mcp-server"
                )
                
        except aiohttp.ClientError as e:
            return None
    
    async def close(self):
        if self.session:
            await self.session.close()
```

## FastMCP Server Integration (Simplified)

FastMCP 2.11+ provides a much simpler way to run servers with built-in auth. Here's how to replace your uvicorn setup:

```python
import os
from fastmcp import FastMCP
from proms_mcp.auth import AuthMode

# Create your custom verifier
def create_token_verifier():
    k8s_api_url = os.getenv("KUBERNETES_API_URL", "https://kubernetes.default.svc")
    ca_cert_path = os.getenv("KUBERNETES_CA_CERT", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    
    return OpenShiftTokenVerifier(
        k8s_api_server_url=k8s_api_url,
        ca_cert_path=ca_cert_path if os.path.exists(ca_cert_path) else None
    )

def main() -> None:
    """Main entry point with FastMCP built-in auth."""
    
    # Configure authentication if needed
    auth_mode = os.getenv("AUTH_MODE", "active").lower()
    auth_provider = None
    if auth_mode == "active":
        auth_provider = create_token_verifier()
    
    # Create your FastMCP server instance with auth
    app = FastMCP(
        name="openshift-mcp-server",
        auth=auth_provider  # Pass auth provider directly to constructor
    )
    
    # Add your tools, resources, etc.
    # @app.tool
    # def your_tool(): pass
    
    # Use FastMCP's built-in ASGI app with uvicorn (still needed)
    import uvicorn
    asgi_app = app.http_app(path="/mcp", transport="streamable-http")
    
    uvicorn.run(
        asgi_app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000"))
    )

if __name__ == "__main__":
    main()
```

## Key Improvements:

1. **No Custom Middleware**: FastMCP handles auth middleware internally
2. **Simplified Auth Integration**: Pass auth provider directly to FastMCP constructor
3. **Automatic Token Extraction**: FastMCP extracts bearer tokens automatically
4. **TokenReview API**: Works for both JWT and opaque tokens universally
5. **Cleaner Code**: Remove custom middleware and manual ASGI wrapping

## Environment Variables:

```bash
# Required
KUBERNETES_API_URL=https://api.your-cluster.com:6443

# Optional
KUBERNETES_CA_CERT=/path/to/ca.crt  # Or omit for insecure dev
AUTH_MODE=active  # or "none" to disable auth
HOST=0.0.0.0
PORT=8000
```

This approach leverages FastMCP's built-in authentication system while providing OpenShift-specific token validation through the standard Kubernetes TokenReview API.
