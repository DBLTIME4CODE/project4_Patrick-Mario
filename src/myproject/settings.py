"""Application settings sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Minimal typed settings model for app configuration."""

    app_name: str = "MyProject"
    app_env: str = "development"
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Read settings from environment with safe defaults."""
    return Settings(
        app_name=os.getenv("APP_NAME", "MyProject"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
