"""Entrypoint for running the application locally."""

from __future__ import annotations

from dotenv import load_dotenv

from myproject.settings import load_settings


def run() -> str:
    """Initialize environment and return startup message."""
    load_dotenv()
    settings = load_settings()
    return f"{settings.app_name} running in {settings.app_env} mode"


if __name__ == "__main__":
    print(run())
