"""Configuration loader for Grafana datasource YAML files."""

import os
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()


@dataclass
class PrometheusDataSource:
    """Prometheus datasource configuration."""

    name: str
    url: str
    auth_header_name: str | None = None
    auth_header_value: str | None = None


class ConfigLoader:
    """Loads and parses Grafana datasource configuration files."""

    def __init__(
        self,
        datasources_file: str = "/etc/grafana/provisioning/datasources/datasources.yaml",
    ):
        self.datasources_file = Path(datasources_file)
        self.datasources: dict[str, PrometheusDataSource] = {}

    def load_datasources(self) -> dict[str, PrometheusDataSource]:
        """Load all Prometheus datasources from the YAML file."""
        if not self.datasources_file.exists():
            logger.warning(
                "Datasources file does not exist", file=str(self.datasources_file)
            )
            return {}

        try:
            self._load_yaml_file(self.datasources_file)
        except Exception as e:
            logger.error(
                "Failed to load datasources file",
                file=str(self.datasources_file),
                error=str(e),
            )

        return self.datasources

    def _load_yaml_file(self, yaml_file: Path) -> None:
        """Load datasources from the YAML file."""
        with open(yaml_file) as f:
            content = yaml.safe_load(f)

        if not content or "datasources" not in content:
            return

        for ds_config in content["datasources"]:
            # Skip non-prometheus datasources
            if ds_config.get("type") != "prometheus":
                continue

            try:
                datasource = self._parse_datasource(ds_config)
                self.datasources[datasource.name] = datasource
            except Exception as e:
                logger.error(
                    "Failed to parse datasource",
                    name=ds_config.get("name"),
                    error=str(e),
                )
                continue

    def _parse_datasource(self, ds_config: dict) -> PrometheusDataSource:
        """Parse a single datasource configuration."""
        # Extract authentication headers
        json_data = ds_config.get("jsonData", {})
        secure_json_data = ds_config.get("secureJsonData", {})

        auth_header_name = json_data.get("httpHeaderName1")
        auth_header_value = secure_json_data.get("httpHeaderValue1")

        return PrometheusDataSource(
            name=ds_config["name"],
            url=ds_config["url"],
            auth_header_name=auth_header_name,
            auth_header_value=auth_header_value,
        )

    def get_datasource(self, name: str) -> PrometheusDataSource | None:
        """Get a specific datasource by name."""
        return self.datasources.get(name)

    def list_datasource_names(self) -> list[str]:
        """Get list of all datasource names."""
        return list(self.datasources.keys())

    def reload(self) -> dict[str, PrometheusDataSource]:
        """Reload datasources from files."""
        self.datasources.clear()
        return self.load_datasources()


def get_config_loader() -> ConfigLoader:
    """Get configured config loader instance."""
    datasources_file = os.getenv(
        "GRAFANA_DATASOURCES_PATH",
        "/etc/grafana/provisioning/datasources/datasources.yaml",
    )
    return ConfigLoader(datasources_file)
