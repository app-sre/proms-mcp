# Promesh MCP Server Makefile
# Development commands for the FastMCP-based Prometheus server

.PHONY: help install lint format test run build clean
.DEFAULT_GOAL := help

# Default values
DATASOURCES_YAML ?= local_config/datasources.yaml
IMAGE_NAME ?= promesh-mcp
PORT ?= 8000

# Detect container engine
CONTAINER_ENGINE := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo "")
ifeq ($(CONTAINER_ENGINE),)
$(error Neither podman nor docker found. Please install one of them.)
endif

help:
	@echo "Promesh MCP Server - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  install     Install dependencies"
	@echo ""
	@echo "Development:"
	@echo "  lint        Run linting and type checks"
	@echo "  format      Format code and fix imports"
	@echo "  test        Run tests with coverage"
	@echo "  run         Start development server"
	@echo ""
	@echo "Container:"
	@echo "  build       Build container image"
	@echo "  clean       Clean temporary files"
	@echo ""
	@echo "Environment Variables:"
	@echo "  DATASOURCES_YAML  Path to datasources config (default: $(DATASOURCES_YAML))"
	@echo "  IMAGE_NAME        Container image name (default: $(IMAGE_NAME))"
	@echo "  PORT              Server port (default: $(PORT))"
	@echo ""
	@echo "Container Engine: $(notdir $(CONTAINER_ENGINE))"

install:
	@echo "Installing dependencies..."
	uv sync
	@echo "✅ Dependencies installed"

format:
	@echo "Formatting code..."
	uv run ruff check --fix promesh_mcp/ tests/
	uv run ruff check --select I --fix promesh_mcp/ tests/
	uv run ruff format promesh_mcp/ tests/
	@echo "✅ Code formatted"

lint:
	@echo "Running linting checks..."
	uv run ruff check promesh_mcp/ tests/
	@echo "Running type checks..."
	uv run mypy promesh_mcp/ tests/
	@echo "✅ Linting and type checking passed"

test:
	@echo "Running tests with coverage..."
	PYTHONPATH=. uv run pytest --cov --cov-report=html --cov-report=term
	@echo "✅ Coverage report generated in htmlcov/"

run:
	@echo "Starting development server..."
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
	GRAFANA_DATASOURCES_PATH="$(DATASOURCES_YAML)" uv run python -m promesh_mcp

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
