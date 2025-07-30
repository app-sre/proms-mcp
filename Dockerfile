# Multi-stage Dockerfile for proms-mcp
# Uses Red Hat UBI as base image with Python

# Base stage with Red Hat UBI Python image
FROM registry.redhat.io/ubi9/python-312:9.6-1753200829@sha256:95ec8d3ee9f875da011639213fd254256c29bc58861ac0b11f290a291fa04435 AS base

# Set working directory
WORKDIR /app

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:0.7.21@sha256:a64333b61f96312df88eafce95121b017cbff72033ab2dbc6398edb4f24a75dd /uv /bin/uv

# Python and UV related variables
ENV \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true \
    UV_NO_PROGRESS=true \
    VIRTUAL_ENV="/app/.venv" \
    PATH="/app/.venv/bin:${PATH}"

# Builder stage for installing dependencies
FROM base AS builder

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Test lock file is up to date
RUN uv lock --locked

# Install dependencies (excluding dev dependencies)
RUN uv sync --frozen --no-group dev --no-install-project --python /usr/bin/python3.12

# Copy source code
COPY README.md ./
COPY proms_mcp ./proms_mcp

# Sync the project
RUN uv sync --frozen --no-group dev

# Test stage - runs the test suite
FROM builder AS test

# Install test dependencies
RUN uv sync --frozen

# Copy test files
COPY tests ./tests

# Run tests
RUN PYTHONPATH=. uv run pytest --cov --cov-report=html --cov-report=term

# Production stage - final runtime image
FROM base AS prod

# Copy the virtual environment with dependencies from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source and project files
COPY --from=builder /app/proms_mcp ./proms_mcp
COPY --from=builder /app/README.md ./
COPY --from=builder /app/pyproject.toml ./

# Expose ports
EXPOSE 8000 8080

# Health check handled by OpenShift probes

# Run the FastMCP server
CMD ["uv", "run", "python", "-m", "proms_mcp"] 
