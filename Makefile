# Proms MCP Server Makefile
# Development commands for the FastMCP-based Prometheus server

.PHONY: help install lint format test run run-auth check-datasources build clean
.DEFAULT_GOAL := help

# Default values
DATASOURCES_YAML ?= local_config/datasources.yaml
IMAGE_NAME ?= proms-mcp
PORT ?= 8000

# Authentication defaults for run-auth target
OPENSHIFT_API_URL ?= 
OPENSHIFT_SERVICE_ACCOUNT_TOKEN ?= 

# Detect container engine
CONTAINER_ENGINE := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo "")
ifeq ($(CONTAINER_ENGINE),)
$(error Neither podman nor docker found. Please install one of them.)
endif

help:
	@echo "Proms MCP Server - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  install     Install dependencies"
	@echo ""
	@echo "Development:"
	@echo "  lint        Run linting and type checks"
	@echo "  format      Format code and fix imports"
	@echo "  test        Run tests with coverage"
	@echo "  run         Start development server (no authentication)"
	@echo "  run-auth    Start development server with OpenShift authentication"
	@echo ""
	@echo "Container:"
	@echo "  build       Build container image"
	@echo "  clean       Clean temporary files"
	@echo ""
	@echo "Environment Variables:"
	@echo "  DATASOURCES_YAML              Path to datasources config (default: $(DATASOURCES_YAML))"
	@echo "  IMAGE_NAME                     Container image name (default: $(IMAGE_NAME))"
	@echo "  PORT                           Server port (default: $(PORT))"
	@echo "  OPENSHIFT_API_URL              OpenShift API URL (required for run-auth)"
	@echo "  OPENSHIFT_SERVICE_ACCOUNT_TOKEN Service account token (optional for run-auth)"
	@echo ""
	@echo "Container Engine: $(notdir $(CONTAINER_ENGINE))"

install:
	@echo "Installing dependencies..."
	uv sync
	@echo "✅ Dependencies installed"

format:
	@echo "Formatting code..."
	uv run ruff check --fix proms_mcp/ tests/
	uv run ruff check --select I --fix proms_mcp/ tests/
	uv run ruff format proms_mcp/ tests/
	@echo "✅ Code formatted"

lint:
	@echo "Running linting checks..."
	uv run ruff check proms_mcp/ tests/
	@echo "Running type checks..."
	uv run mypy proms_mcp/ tests/
	@echo "✅ Linting and type checking passed"

test:
	@echo "Running tests with coverage..."
	PYTHONPATH=. uv run pytest --cov --cov-report=html --cov-report=term
	@echo "✅ Coverage report generated in htmlcov/"

check-datasources:
	@if [ ! -f "$(DATASOURCES_YAML)" ]; then \
		echo "❌ Datasources config not found: $(DATASOURCES_YAML)"; \
		echo ""; \
		echo "Please create a datasources.yaml file."; \
		echo "You can copy and modify the example:"; \
		echo "  cp local_config/datasources-example.yaml $(DATASOURCES_YAML)"; \
		echo ""; \
		exit 1; \
	fi
	@echo "Using datasources config: $(DATASOURCES_YAML)"

run: check-datasources
	@echo "Starting development server (no authentication)..."
	AUTH_MODE=none GRAFANA_DATASOURCES_PATH="$(DATASOURCES_YAML)" uv run python -m proms_mcp

run-auth: check-datasources
	@echo "Starting authenticated development server..."
	@if [ -z "$(OPENSHIFT_API_URL)" ]; then \
		echo "❌ OPENSHIFT_API_URL is required for authenticated mode"; \
		echo ""; \
		echo "Usage:"; \
		echo "     make run-auth OPENSHIFT_API_URL=https://api.cluster.example.com:6443"; \
		echo ' or  make run-auth OPENSHIFT_API_URL=$(oc whoami --show-server)'; \
		echo ""; \
		exit 1; \
	fi
	@echo "Using OpenShift API: $(OPENSHIFT_API_URL)"
	AUTH_MODE=active OPENSHIFT_API_URL="$(OPENSHIFT_API_URL)" GRAFANA_DATASOURCES_PATH="$(DATASOURCES_YAML)" uv run python -m proms_mcp

build:
	@echo "Building container image with $(notdir $(CONTAINER_ENGINE))..."
	$(CONTAINER_ENGINE) build -t $(IMAGE_NAME) .
	@echo "✅ Container image built: $(IMAGE_NAME)"

clean:
	@echo "Cleaning up..."
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf __pycache__
	rm -rf */__pycache__
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	@echo "✅ Cleanup completed" 
