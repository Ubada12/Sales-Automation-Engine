"""
config.py

Configuration loader for SAP Automation Engine.

Responsibilities:
- Load config.yaml
- Validate required sections
- Provide immutable configuration access
- Fail safely on invalid configuration
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


class ConfigurationError(Exception):
    """
    Raised when configuration loading fails.
    """
    pass


class Config:
    """
    Configuration manager.

    Loads YAML once during startup and provides
    centralized access across application modules.
    """

    REQUIRED_SECTIONS = {
        "logging",
        "performance",
        "recovery",
        "ui",
        "workbook",
        "output",
        "validation",
        "debug",
    }

    def __init__(self, config_path: Path) -> None:
        """
        Initialize configuration.

        Args:
            config_path:
                Path to config.yaml
        """

        self._config_path = config_path
        self._data: Dict[str, Any] = {}

        self._load()

    def _load(self) -> None:
        """
        Load YAML configuration.

        Raises:
            ConfigurationError
        """

        if not self._config_path.exists():
            raise ConfigurationError(
                f"Configuration file not found: {self._config_path}"
            )

        try:

            with self._config_path.open(
                "r",
                encoding="utf-8"
            ) as file:

                loaded = yaml.safe_load(file)

        except yaml.YAMLError as exc:

            raise ConfigurationError(
                f"Invalid YAML: {exc}"
            ) from exc

        except OSError as exc:

            raise ConfigurationError(
                f"Unable to read configuration: {exc}"
            ) from exc

        if not isinstance(loaded, dict):

            raise ConfigurationError(
                "Configuration root must be dictionary"
            )

        missing = self.REQUIRED_SECTIONS - loaded.keys()

        if missing:

            raise ConfigurationError(
                f"Missing config sections: {sorted(missing)}"
            )

        self._data = loaded

    def get(
        self,
        section: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read config value.

        Args:
            section:
                YAML top level section

            key:
                Nested key

            default:
                Default fallback

        Returns:
            Configuration value
        """

        return (
            self._data
            .get(section, {})
            .get(key, default)
        )

    @property
    def raw(self) -> Dict[str, Any]:
        """
        Entire config.

        Returns:
            Config dictionary
        """

        return self._data.copy()