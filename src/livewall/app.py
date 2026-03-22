"""Main LiveWall application — ties player, tray, X11 and monitors together."""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import signal
import sys
from pathlib import Path
from typing import IO, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from livewall.autostart import install_autostart, remove_autostart
from livewall.config import CONFIG_DIR, load_config, save_config
from livewall.player import SUPPORTED_FORMATS, WallpaperPlayer
from livewall.power import is_on_battery
from livewall.settings_dialog import SettingsDialog
from livewall.tray import LiveWallTray
from livewall.x11 import has_fullscreen_window, set_desktop_window_type

logger = logging.getLogger(__name__)

PID_FILE = CONFIG_DIR / "livewall.pid"
_MONITOR_INTERVAL_MS = 5_000


class LiveWallApp:
    """Top-level controller — one instance per process."""

    def __init__(self) -> None:
        self._lock_fd: IO[str] | None = None
        self._ensure_single_instance()

        self._config = load_config()

        self._qt_app = QApplication(sys.argv)
        self._qt_app.setQuitOnLastWindowClosed(False)
        self._qt_app.setApplicationName("LiveWall")

        self._widget = self._create_wallpaper_widget()
        self._player = WallpaperPlayer(wid=int(self._widget.winId()))
        self._apply_player_settings()

        self._tray = LiveWallTray(
            on_toggle_pause=self._toggle_pause,
            on_next=self._next_wallpaper,
            on_settings=self._show_settings,
            on_quit=self._quit,
        )

        self._user_paused = False
        self._auto_paused = False

        # Periodic monitor for fullscreen / battery
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._monitor_check)
        self._monitor_timer.start(_MONITOR_INTERVAL_MS)

        self._register_cleanup()

        # Begin playback
        if self._config.wallpaper_path:
            self._player.play(self._config.wallpaper_path)
            logger.info("LiveWall started")

    # ------------------------------------------------------------------
    # Wallpaper widget
    # ------------------------------------------------------------------

    def _create_wallpaper_widget(self) -> QWidget:
        widget = QWidget()
        widget.setWindowTitle("LiveWall")
        widget.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        widget.setStyleSheet("background:black;")

        screen = self._qt_app.primaryScreen()
        if screen is not None:
            widget.setGeometry(screen.geometry())

        widget.show()

        try:
            set_desktop_window_type(int(widget.winId()))
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not set desktop window type: %s", exc)

        return widget

    # ------------------------------------------------------------------
    # Player helpers
    # ------------------------------------------------------------------

    def _apply_player_settings(self) -> None:
        self._player.set_volume(self._config.volume)
        self._player.set_mute(self._config.mute)

    # ------------------------------------------------------------------
    # Tray callbacks
    # ------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        if self._user_paused:
            self._user_paused = False
            self._auto_paused = False
            self._player.resume()
            self._tray.update_play_state(playing=True)
        else:
            self._user_paused = True
            self._player.pause()
            self._tray.update_play_state(playing=False)

    def _next_wallpaper(self) -> None:
        wp_dir = Path(self._config.wallpaper_dir)
        if not wp_dir.is_dir():
            logger.warning("Wallpaper directory not found: %s", wp_dir)
            return

        files = sorted(f for f in wp_dir.iterdir() if f.suffix.lower() in SUPPORTED_FORMATS)
        if not files:
            logger.warning("No wallpaper files in %s", wp_dir)
            return

        current = Path(self._config.wallpaper_path) if self._config.wallpaper_path else None
        try:
            idx = files.index(current) if current else -1
        except ValueError:
            idx = -1
        next_file = files[(idx + 1) % len(files)]

        self._config.wallpaper_path = str(next_file)
        save_config(self._config)
        self._player.play(self._config.wallpaper_path)

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_cfg = dialog.get_config()
            old_path = self._config.wallpaper_path
            self._config = new_cfg
            save_config(self._config)
            self._apply_player_settings()

            if self._config.autostart:
                install_autostart()
            else:
                remove_autostart()

            if self._config.wallpaper_path and self._config.wallpaper_path != old_path:
                self._player.play(self._config.wallpaper_path)

    # ------------------------------------------------------------------
    # Monitor: fullscreen & battery
    # ------------------------------------------------------------------

    def _monitor_check(self) -> None:
        if self._user_paused:
            return

        should_pause = False
        try:
            if has_fullscreen_window():
                should_pause = True
        except Exception:  # noqa: BLE001
            pass

        if not should_pause:
            try:
                if is_on_battery():
                    should_pause = True
            except Exception:  # noqa: BLE001
                pass

        if should_pause and not self._auto_paused:
            self._player.pause()
            self._auto_paused = True
            logger.info("Auto-paused (fullscreen / battery)")
        elif not should_pause and self._auto_paused:
            self._player.resume()
            self._auto_paused = False
            logger.info("Auto-resumed")

    # ------------------------------------------------------------------
    # Single-instance lock
    # ------------------------------------------------------------------

    def _ensure_single_instance(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock_fd = open(PID_FILE, "w", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("LiveWall is already running")
            sys.exit(1)
        self._lock_fd.write(str(os.getpid()))
        self._lock_fd.flush()

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except OSError:
                pass
            PID_FILE.unlink(missing_ok=True)
            self._lock_fd = None

    # ------------------------------------------------------------------
    # Cleanup & shutdown
    # ------------------------------------------------------------------

    def _register_cleanup(self) -> None:
        atexit.register(self._cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        logger.info("Received signal %d — shutting down", signum)
        self._quit()

    def _cleanup(self) -> None:
        try:
            self._player.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._widget.close()
        except Exception:  # noqa: BLE001
            pass
        self._release_lock()
        logger.info("LiveWall cleanup complete")

    def _quit(self) -> None:
        self._cleanup()
        self._qt_app.quit()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Enter the Qt event loop. Returns the exit code."""
        return self._qt_app.exec()
