"""XDG autostart .desktop file management."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "livewall.desktop"

_DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Name=LiveWall
Comment=Video wallpaper engine for KDE Plasma
Exec=livewall --start
Hidden=false
X-GNOME-Autostart-enabled=true
"""


def install_autostart() -> None:
    """Create the XDG autostart .desktop file."""
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(_DESKTOP_ENTRY, encoding="utf-8")
    logger.info("Installed autostart entry: %s", DESKTOP_FILE)


def remove_autostart() -> None:
    """Remove the XDG autostart .desktop file if it exists."""
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()
        logger.info("Removed autostart entry: %s", DESKTOP_FILE)
