# LLM Development Guide for Promesh MCP Server

This document provides comprehensive guidance for Large Language Models (LLMs) working on the Promesh MCP Server codebase. Follow these rules and best practices to maintain code quality and project consistency.

**Note**: `GEMINI.md` is a symlink to this file to provide model-specific guidance. The same pattern applies to `.cursor/rules/llm.d` for IDE integration.

## 🚀 Quick Reference

### Critical Commands
- `make lint`: Run linting and type checks
- `make test`: Run tests with coverage report
- `make run`: Start development server (requires datasources.yaml)
- `make format`: Format code and fix imports
- `make help`: Show all available commands

### Workflow Checklist
**Before making changes:**
1. Run `make test` to ensure clean starting point
2. Follow established decorator patterns
3. Maintain test coverage >75%

**After making changes:**
1. Run `make format` then `make lint` for code quality
2. Run `make test` to ensure all tests pass
3. Ensure zero linting/type errors
4. Update SPECS.md if architecture changed

## 🎯 Core Principles

### 1. **Always Test First**
- **MANDATORY**: Run tests after every code change
- **Command**: `make test` or `PYTHONPATH=. uv run pytest -v`
- **Coverage**: Maintain >75% test coverage with `make test-cov`
- **Fix Failures**: Never leave failing tests - fix them immediately
- **Add Tests**: When adding new features, add corresponding tests

### 2. **Code Quality is Non-Negotiable**
- **Linting**: Always run `make lint` or `uv run ruff check`
- **Formatting**: Always run `make format` or `uv run ruff format`
- **Import Sorting**: Included in format command (`ruff check --select I --fix`)
- **Zero Tolerance**: No linting errors should remain
- **Quick Check**: Use `make quick-test` for rapid validation

### 3. **Keep Documentation Updated**
- **LLM.md**: MUST be updated when new development rules are defined or existing ones change
- **SPECS.md**: MUST be updated when making architectural changes (technical specification)
- **README.md**: MUST be updated if user-facing changes are made (user documentation)
- **Docstrings**: All functions must have clear docstrings
- **Type Hints**: All functions must have proper type annotations

**Documentation Hierarchy:**
- `LLM.md`: Instructions for LLMs working on this codebase
- `README.md`: Documentation for real users of the tool
- `SPECS.md`: Technical specification for the tool's architecture and implementation
- **All three must be kept synchronized and up-to-date**

## 🏗️ Architecture Understanding

### FastMCP Server Pattern
This project uses the modern FastMCP library with `@app.tool()` decorators:

```python
@app.tool()
@tool_error_handler
async def my_tool(param: str) -> str:
    """Clear docstring describing the tool."""
    # Implementation here
    return format_tool_response(result)
```

### Key Components
1. **`server.py`**: FastMCP server with 9 MCP tools using decorators
2. **`prometheus_client.py`**: Prometheus API wrapper with security validation
3. **`config_loader.py`**: Grafana datasource YAML parser
4. **Error Handling**: Uses decorator patterns to reduce code duplication

### Decorator Patterns
The codebase uses two key decorators to eliminate repetitive code:
- `@tool_error_handler`: Handles common MCP tool errors and validation
- `@prometheus_error_handler`: Handles Prometheus API errors and logging

## 📋 Development Workflow

### Before Making Changes
1. **Understand the Context**: Read relevant code and tests
2. **Check Current State**: Run `make test` to ensure starting point is clean
3. **Plan Changes**: Consider impact on SPECS.md and documentation

### Making Changes
1. **Small Iterations**: Make incremental changes
2. **Test Frequently**: Run `make quick-test` after each change
3. **Follow Patterns**: Use existing decorator patterns and conventions
4. **Maintain Types**: Keep all type annotations up to date

### After Making Changes
1. **Full Test Suite**: Run `make test-cov` to verify everything works
2. **Code Quality**: Run `make format` and `make lint`
3. **Update Docs**: Update SPECS.md if architecture changed
4. **Final Validation**: Run `make qa` for complete quality check

## 🧪 Testing Guidelines

### Test Quality Standards
**Tests must meet the same quality standards as production code:**
- **Linting**: All test files are linted with `ruff` (included in `make lint`)
- **Formatting**: All test files are formatted with `ruff format` (included in `make format`)
- **Type Checking**: All test files are type-checked with `mypy` (included in `make type-check`)
- **Documentation**: Test functions should have clear docstrings explaining what they test

### Test Coverage Requirements
- **Minimum**: 75% overall coverage
- **New Code**: 90%+ coverage for new features
- **Critical Paths**: 100% coverage for security and error handling

### Test Categories
- **Unit Tests**: Test individual functions in isolation
- **Integration Tests**: Test component interactions
- **Error Handling**: Test all error conditions and edge cases
- **Security Tests**: Validate PromQL security patterns

### Test Organization
- **Location**: Tests are in the root `tests/` directory (separate from package code)
- **Structure**: Test file structure mirrors the `promesh_mcp/` package structure
- **Naming**: Test files follow `test_*.py` pattern matching the module they test

### Running Tests
```bash
make test          # Run tests with coverage report
make qa            # Full quality assurance (format + lint + test)
make lint          # Lint both promesh_mcp/ and tests/ directories
make format        # Format both promesh_mcp/ and tests/ directories
make type-check    # Type check both promesh_mcp/ and tests/ directories
```

## 🔧 Code Patterns and Conventions

### Error Handling
Always use the decorator patterns instead of repetitive try/catch blocks:

```python
# ✅ GOOD - Use decorator
@tool_error_handler
async def my_tool(datasource_id: str) -> str:
    datasource, error = validate_datasource(datasource_id)
    if error:
        return format_tool_response(None, "error", error)
    # ... implementation

# ❌ BAD - Repetitive error handling
async def my_tool(datasource_id: str) -> str:
    try:
        if not config_loader:
            return format_tool_response(None, "error", "Server not initialized")
        # ... repetitive boilerplate
```

### Response Formatting
Always use `format_tool_response()` for consistent JSON responses:

```python
# Success
return format_tool_response(data, datasource=datasource_id)

# Error
return format_tool_response(None, "error", error_message, datasource=datasource_id)

# Query result
return format_tool_response(result["data"], datasource=datasource_id, query=promql)
```

### Logging
Use structured logging with correlation IDs:

```python
logger.info("Operation started", 
           datasource=datasource_id, 
           correlation_id=correlation_id)
```

## 🚨 Critical Rules

### Never Do This
- ❌ Leave failing tests
- ❌ Commit without running linting/formatting
- ❌ Add dependencies without updating pyproject.toml
- ❌ Change architecture without updating SPECS.md
- ❌ Create repetitive error handling code
- ❌ Skip type annotations
- ❌ Remove security validations

### Always Do This
- ✅ Run `make qa` before considering changes complete
- ✅ Use existing decorator patterns for error handling
- ✅ Add tests for new functionality
- ✅ Update LLM.md when defining new development rules
- ✅ Update SPECS.md for architectural changes
- ✅ Update README.md for user-facing changes
- ✅ Follow the established code patterns
- ✅ Maintain or improve test coverage
- ✅ Keep docstrings and type hints updated

## 🛠️ Development Commands

### Essential Makefile Commands
```bash
make help          # Show all available commands
make install       # Install dependencies
make run           # Start development server (requires datasources.yaml)
make qa            # Full quality assurance (format + lint + test)
make type-check    # Run type checks only
make build         # Build container image (auto-detects podman/docker)
make clean         # Clean temporary files
```

### Manual Commands (if needed)
```bash
# Testing
PYTHONPATH=. uv run pytest --cov --cov-report=html

# Code Quality
uv run ruff check --fix
uv run ruff check --select I --fix
uv run ruff format
uv run mypy .

# Development  
DATASOURCES_YAML=custom.yaml make run  # Use custom config file
PORT=9000 make run                      # Use custom port

# Quick start: copy the example config
cp local_config/datasources-example.yaml local_config/datasources.yaml
```

## 📁 File Organization

### Core Files
- `server.py`: Main FastMCP server (419 lines, highly optimized)
- `prometheus_client.py`: Prometheus client (377 lines, decorator-based)
- `config_loader.py`: Configuration management (158 lines)

### Supporting Files
- `pyproject.toml`: Dependencies and project config
- `Makefile`: Development workflow automation
- `Dockerfile`: Container definition
- `SPECS.md`: Technical specification (MUST be kept updated)
- `README.md`: User documentation

### Test Files
- `tests/test_server_fastmcp.py`: FastMCP server tests
- `tests/test_prometheus_client.py`: Prometheus client tests  
- `tests/test_config_loader.py`: Configuration tests

## 🔍 Code Review Checklist

Before considering any changes complete, verify:

- [ ] All tests pass (`make test`)
- [ ] Code coverage is maintained (`make test-cov`)
- [ ] No linting errors (`make lint`)
- [ ] No type checking errors (`make type-check`)
- [ ] Code is properly formatted (`make format`)
- [ ] LLM.md is updated if new development rules are defined
- [ ] SPECS.md is updated if architecture changed
- [ ] README.md is updated if user-facing changes are made
- [ ] New functionality has tests
- [ ] Error handling uses decorator patterns
- [ ] Type annotations are present and correct
- [ ] Docstrings are clear and helpful
- [ ] Security validations are maintained

## 🎓 Key Learnings from Development

### FastMCP Integration
- FastMCP with `@app.tool()` decorators is much cleaner than manual MCP implementation
- StreamableHTTP transport handles all protocol complexity automatically
- Tools should return JSON strings, not complex objects

### Decorator Pattern Benefits
- Eliminates 100+ lines of repetitive error handling code
- Centralizes logging and correlation ID management
- Makes adding new tools trivial
- Improves maintainability significantly

### Testing Strategy
- Mock external dependencies (Prometheus API calls)
- Test both success and error paths
- Use correlation IDs for debugging
- Maintain high coverage on critical paths

### Dependencies Management
- Keep dependencies minimal (6 core dependencies)
- Use `uv` for fast dependency management
- Avoid unnecessary frameworks (removed FastAPI/uvicorn)

### Development Workflow
- Makefile automation is essential for consistency
- Quick feedback loops improve productivity
- Comprehensive CI pipeline catches issues early

## 🚀 Success Metrics

A successful change should:
- Pass all 44 tests
- Maintain >75% test coverage  
- Have zero linting errors
- Follow established patterns
- Update documentation as needed
- Be deployable immediately

Remember: **Quality is not negotiable. Every change must maintain the high standards established in this codebase.** 
