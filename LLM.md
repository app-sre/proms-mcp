# LLM Development Guide for Proms MCP Server

> **Note**: This file is also available as `GEMINI.md` and `.cursor/rules/LLM.md` (both are symlinks to this file).

Essential workflow guidance for AI assistants working on this codebase.

## 🚀 Quick Commands

```bash
make test          # Run tests (ALWAYS run after changes)
make format        # Format code 
make lint          # Check code quality
make run           # Start server (needs datasources.yaml)
git --no-pager     # Use --no-pager flag for all git commands to avoid pagination
```

## 🎯 Core Rules

### 1. LEAN Development Philosophy
- **Don't reinvent the wheel** - Use existing, proven libraries when available
- **Minimal viable changes** - Add functionality without over-engineering
- **Build on solid foundations** - Extend existing working systems rather than replacing them
- **Keep it simple** - Prefer straightforward solutions over complex architectures

### 2. Test-Driven Workflow
- **ALWAYS** run `make test` after any code change
- Maintain >90% test coverage
- Fix failing tests immediately - never leave them broken

### 3. Code Quality Standards
- Run `make format` then `make lint` before finishing
- Zero tolerance for linting errors
- All functions need type hints and docstrings

### 4. Documentation Sync
- **LLM.md**: Update when changing development rules
- **SPECS.md**: Update for architectural changes  
- **README.md**: Update for user-facing changes

## 🏗️ Architecture Patterns

### FastMCP Tools
Use the established decorator pattern:

```python
@app.tool()
@mcp_access_log("tool_name")
@tool_error_handler
async def my_tool(param: str) -> str:
    """Clear docstring."""
    datasource, error = validate_datasource(datasource_id)
    if error:
        return format_tool_response(None, "error", error)
    # Implementation
    return format_tool_response(result, datasource=datasource_id)
```

### Key Components
- **`server.py`**: 8 MCP tools with decorators
- **`client.py`**: Prometheus API wrapper with validation
- **`config.py`**: Grafana datasource parser

## 📋 Development Workflow

1. **Before Changes**: Run `make test` to ensure clean state
2. **During Changes**: Make small incremental changes
3. **After Changes**: Run `make format lint test` for full validation

## 🚨 Critical Don'ts

- ❌ Skip tests or leave them failing
- ❌ Commit without running `make format lint test`
- ❌ Add repetitive error handling (use decorators)
- ❌ Change architecture without updating SPECS.md
- ❌ Remove security validations
- ❌ Reinvent functionality that exists in proven libraries
- ❌ Over-engineer simple solutions

## ✅ Always Do

- ✅ Use existing decorator patterns
- ✅ Run `make format lint test` before considering work complete
- ✅ Add tests for new functionality
- ✅ Keep documentation synchronized
- ✅ Follow established code patterns
- ✅ Use `git --no-pager` for all git commands
- ✅ Research existing libraries before building custom solutions
- ✅ Extend existing systems rather than replacing them

## 🔧 File Structure

```
proms_mcp/
  server.py        # Main FastMCP server (8 tools)
  client.py        # Prometheus API wrapper  
  config.py        # Config parser
  monitoring.py    # Health/metrics endpoints
tests/             # Test suite (mirrors package structure)
```

## 🎯 Success Criteria

A good change:
- Passes all tests (`make test`)
- Has zero linting errors (`make lint`) 
- Maintains test coverage
- Updates relevant documentation
- Follows established patterns

**Remember**: This is a lean, production-ready codebase. Keep changes minimal and focused. 
