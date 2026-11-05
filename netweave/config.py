"""Configuration management for netweave."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class Settings:
    """Global configuration settings for netweave.

    Parameters
    ----------
    log_folder : str
        Directory for log files.
    log_file : str
        Name of the log file.
    log_console : bool
        Whether to log messages to the console.
    log_level : str
        Logging level (DEBUG, INFO, WARNING, ERROR).
    debug : bool
        If True, enable verbose logging to console and write structured logs
        to file. If False (default), only concise status messages are shown.
    gtfs_api : dict[str, str]
        Mapping of GTFS feed source names to API base URLs.
    """

    log_folder: str = field(default="logs")
    log_file: str = field(default="netweave.log")
    log_console: bool = field(default=True)
    log_level: str = field(default="INFO")
    debug: bool = field(default=False)
    gtfs_api: dict[str, str] = field(
        default_factory=lambda: {
            "transitland": "https://transit.land/api/v2/rest",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        """Return settings as a plain dictionary."""
        return {
            "log_folder": self.log_folder,
            "log_file": self.log_file,
            "log_console": self.log_console,
            "log_level": self.log_level,
            "debug": self.debug,
            "gtfs_api": self.gtfs_api,
        }

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        """Load settings from a YAML file.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to the YAML file.

        Returns
        -------
        Settings
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Settings file not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: str | Path) -> None:
        """Save settings to a YAML file.

        Parameters
        ----------
        path : str or pathlib.Path
            Path to write the YAML file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)


# Global settings instance — users can replace this with their own
settings = Settings()
