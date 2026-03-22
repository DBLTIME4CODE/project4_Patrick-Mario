"""CLI entry point for LiveWall (``livewall`` command)."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from livewall.config import CONFIG_DIR, load_config, save_config

logger = logging.getLogger(__name__)

PID_FILE = CONFIG_DIR / "livewall.pid"


def main() -> None:
    """Parse arguments and dispatch to the appropriate sub-command."""
    parser = argparse.ArgumentParser(
        prog="livewall",
        description="LiveWall — video wallpaper engine for KDE Plasma / X11",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--start", action="store_true", help="Start LiveWall (default)")
    group.add_argument("--stop", action="store_true", help="Stop the running instance")
    group.add_argument("--set", metavar="PATH", help="Set wallpaper path in config")

    args = parser.parse_args()

    if args.stop:
        _stop_running()
    elif args.set:
        _set_wallpaper(args.set)
    else:
        _start()


# ------------------------------------------------------------------
# Sub-commands
# ------------------------------------------------------------------


def _start() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # Deferred import so --stop / --set don't need Qt or mpv
    from livewall.app import LiveWallApp

    app = LiveWallApp()
    sys.exit(app.run())


def _stop_running() -> None:
    if not PID_FILE.exists():
        print("LiveWall is not running.")
        sys.exit(1)
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to LiveWall (PID {pid}).")
    except (ValueError, ProcessLookupError, PermissionError) as exc:
        print(f"Failed to stop LiveWall: {exc}")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)


def _set_wallpaper(path: str) -> None:
    resolved = Path(path).resolve()
    if not resolved.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    config = load_config()
    config.wallpaper_path = str(resolved)
    config.wallpaper_dir = str(resolved.parent)
    save_config(config)
    print(f"Wallpaper set to: {resolved}")
    print("Restart LiveWall to apply the change.")
