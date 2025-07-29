FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv first (separate layer for better caching)
RUN pip install --no-cache-dir uv

# Copy dependency files and install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# OpenShift will handle user security automatically

# Expose ports
EXPOSE 8000 8080

# Health check handled by OpenShift probes

# Run the FastMCP server
CMD ["uv", "run", "python", "-m", "promesh_mcp"] 
