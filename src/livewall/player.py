"""mpv-based video wallpaper player."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = frozenset({".mp4", ".webm", ".mkv", ".gif"})


class WallpaperPlayer:
    """Wraps a python-mpv ``MPV`` instance embedded in a Qt widget."""

    def __init__(self, wid: int) -> None:
        self._wid = wid
        self._player: Any = None
        self._paused = False
        self._init_mpv()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _init_mpv(self) -> None:
        try:
            import mpv  # type: ignore[import-untyped]
        except ImportError:
            logger.error("python-mpv is not installed (pip install python-mpv)")
            raise RuntimeError("python-mpv library is required but not installed") from None

        try:
            self._player = mpv.MPV(
                wid=str(self._wid),
                input_default_bindings=False,
                osc=False,
                osd_level=0,
                loop="inf",
                keep_open="yes",
                idle="yes",
                cursor_autohide="always",
                stop_screensaver="no",
            )
            logger.info("mpv player initialised (wid=%d)", self._wid)
        except Exception as exc:
            logger.error("Failed to initialise mpv: %s", exc)
            raise RuntimeError(f"Failed to initialise mpv: {exc}") from exc

    def stop(self) -> None:
        """Terminate the mpv process and release resources."""
        if self._player is not None:
            try:
                self._player.terminate()
                logger.info("mpv player terminated")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error terminating mpv: %s", exc)
            finally:
                self._player = None

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def play(self, path: str) -> None:
        """Start playing *path*. Logs a warning for unsupported extensions."""
        if self._player is None:
            logger.error("Player not initialised")
            return
        fp = Path(path)
        if not fp.exists():
            logger.error("Wallpaper file not found: %s", path)
            return
        if fp.suffix.lower() not in SUPPORTED_FORMATS:
            logger.warning("Unsupported format %s — playback may fail", fp.suffix)
        self._player.play(str(fp))
        self._paused = False
        logger.info("Playing: %s", path)

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause = True
            self._paused = True

    def resume(self) -> None:
        if self._player is not None:
            self._player.pause = False
            self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def set_volume(self, volume: int) -> None:
        if self._player is not None:
            self._player.volume = max(0, min(100, volume))

    def set_mute(self, mute: bool) -> None:
        if self._player is not None:
            self._player.mute = mute
