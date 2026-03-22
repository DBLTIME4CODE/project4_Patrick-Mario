"""Persistent JSON configuration for LiveWall."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "livewall"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class LiveWallConfig:
    """LiveWall user-facing settings."""

    wallpaper_path: str = ""
    wallpaper_dir: str = ""
    volume: int = 0
    loop: bool = True
    autostart: bool = False
    mute: bool = True

    def __post_init__(self) -> None:
        if not self.wallpaper_dir:
            self.wallpaper_dir = str(Path.home() / "Videos" / "Wallpapers")


def load_config() -> LiveWallConfig:
    """Load config from disk, returning defaults on any error."""
    if not CONFIG_PATH.exists():
        return LiveWallConfig()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        valid_keys = {f.name for f in fields(LiveWallConfig)}
        filtered = {k: v for k, v in raw.items() if k in valid_keys}
        return LiveWallConfig(**filtered)
    except (json.JSONDecodeError, TypeError, OSError) as exc:
        logger.warning("Failed to load config, using defaults: %s", exc)
        return LiveWallConfig()


def save_config(config: LiveWallConfig) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    logger.info("Config saved to %s", CONFIG_PATH)
