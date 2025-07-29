"""Unit tests for config module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from promesh_mcp.config import (
    ConfigLoader,
    PrometheusDataSource,
    get_config_loader,
)


class TestPrometheusDataSource:
    """Test PrometheusDataSource dataclass."""

    def test_valid_datasource(self) -> None:
        """Test creating a valid datasource."""
        ds = PrometheusDataSource(
            name="test-prometheus",
            url="https://prometheus.example.com",
            auth_header_name="Authorization",
            auth_header_value="Bearer token123",
        )

        assert ds.name == "test-prometheus"
        assert ds.url == "https://prometheus.example.com"
        assert ds.auth_header_name == "Authorization"
        assert ds.auth_header_value == "Bearer token123"

    def test_datasource_without_auth(self) -> None:
        """Test datasource without auth headers."""
        ds = PrometheusDataSource(
            name="test-prometheus",
            url="https://prometheus.example.com",
        )

        assert ds.auth_header_name is None
        assert ds.auth_header_value is None


class TestConfigLoader:
    """Test ConfigLoader class."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.datasources_file = Path(self.temp_dir) / "datasources.yaml"
        self.config_loader = ConfigLoader(str(self.datasources_file))

    def create_test_yaml(self, content: dict) -> Path:
        """Helper to create test YAML file."""
        with open(self.datasources_file, "w") as f:
            yaml.dump(content, f)
        return self.datasources_file

    def test_load_valid_datasources(self) -> None:
        """Test loading valid datasources."""
        content = {
            "apiVersion": 1,
            "prune": True,
            "datasources": [
                {
                    "name": "prod-prometheus",
                    "type": "prometheus",
                    "url": "https://prometheus-prod.example.com",
                    "jsonData": {"httpHeaderName1": "Authorization"},
                    "secureJsonData": {"httpHeaderValue1": "Bearer prod-token"},
                },
                {
                    "name": "staging-prometheus",
                    "type": "prometheus",
                    "url": "https://prometheus-staging.example.com",
                    "jsonData": {"httpHeaderName1": "Authorization"},
                    "secureJsonData": {"httpHeaderValue1": "Bearer staging-token"},
                },
            ],
        }

        self.create_test_yaml(content)
        datasources = self.config_loader.load_datasources()

        assert len(datasources) == 2
        assert "prod-prometheus" in datasources
        assert "staging-prometheus" in datasources

        prod_ds = datasources["prod-prometheus"]
        assert prod_ds.name == "prod-prometheus"
        assert prod_ds.url == "https://prometheus-prod.example.com"
        assert prod_ds.auth_header_name == "Authorization"
        assert prod_ds.auth_header_value == "Bearer prod-token"

    def test_skip_non_prometheus_datasources(self) -> None:
        """Test that non-prometheus datasources are skipped."""
        content = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "prometheus-ds",
                    "type": "prometheus",
                    "url": "https://prometheus.example.com",
                },
                {"name": "loki-ds", "type": "loki", "url": "https://loki.example.com"},
                {
                    "name": "influx-ds",
                    "type": "influxdb",
                    "url": "https://influx.example.com",
                },
            ],
        }

        self.create_test_yaml(content)
        datasources = self.config_loader.load_datasources()

        assert len(datasources) == 1
        assert "prometheus-ds" in datasources
        assert "loki-ds" not in datasources
        assert "influx-ds" not in datasources

    def test_empty_file(self) -> None:
        """Test loading from empty file."""
        self.create_test_yaml({})
        datasources = self.config_loader.load_datasources()
        assert len(datasources) == 0

    def test_nonexistent_file(self) -> None:
        """Test loading from nonexistent file."""
        config_loader = ConfigLoader("/nonexistent/datasources.yaml")
        datasources = config_loader.load_datasources()
        assert len(datasources) == 0

    def test_invalid_yaml_file(self) -> None:
        """Test handling of invalid YAML file."""
        with open(self.datasources_file, "w") as f:
            f.write("invalid: yaml: content: [")

        # Should not raise exception, just return empty dict
        datasources = self.config_loader.load_datasources()
        assert len(datasources) == 0

    def test_yaml_without_datasources(self) -> None:
        """Test YAML file without datasources section."""
        content = {"apiVersion": 1, "prune": True}

        self.create_test_yaml(content)
        datasources = self.config_loader.load_datasources()
        assert len(datasources) == 0

    def test_get_datasource(self) -> None:
        """Test getting specific datasource."""
        content = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "test-prometheus",
                    "type": "prometheus",
                    "url": "https://prometheus.example.com",
                }
            ],
        }

        self.create_test_yaml(content)
        self.config_loader.load_datasources()

        ds = self.config_loader.get_datasource("test-prometheus")
        assert ds is not None
        assert ds.name == "test-prometheus"

        missing_ds = self.config_loader.get_datasource("nonexistent")
        assert missing_ds is None

    def test_list_datasource_names(self) -> None:
        """Test listing datasource names."""
        content = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "ds1",
                    "type": "prometheus",
                    "url": "https://prometheus1.example.com",
                },
                {
                    "name": "ds2",
                    "type": "prometheus",
                    "url": "https://prometheus2.example.com",
                },
            ],
        }

        self.create_test_yaml(content)
        self.config_loader.load_datasources()

        names = self.config_loader.list_datasource_names()
        assert set(names) == {"ds1", "ds2"}

    def test_reload_datasources(self) -> None:
        """Test reloading datasources."""
        # Initial load
        content1 = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "initial-ds",
                    "type": "prometheus",
                    "url": "https://initial.example.com",
                }
            ],
        }

        self.create_test_yaml(content1)
        datasources = self.config_loader.load_datasources()
        assert len(datasources) == 1
        assert "initial-ds" in datasources

        # Update file
        content2 = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "updated-ds",
                    "type": "prometheus",
                    "url": "https://updated.example.com",
                }
            ],
        }

        self.create_test_yaml(content2)
        datasources = self.config_loader.reload()
        assert len(datasources) == 1
        assert "updated-ds" in datasources
        assert "initial-ds" not in datasources


def test_get_config_loader() -> None:
    """Test get_config_loader factory function."""
    with patch.dict(
        "os.environ", {"GRAFANA_DATASOURCES_PATH": "/custom/datasources.yaml"}
    ):
        config_loader = get_config_loader()
        assert config_loader.datasources_file == Path("/custom/datasources.yaml")

    # Test default path
    with patch.dict("os.environ", {}, clear=True):
        config_loader = get_config_loader()
        assert config_loader.datasources_file == Path(
            "/etc/grafana/provisioning/datasources/datasources.yaml"
        )
