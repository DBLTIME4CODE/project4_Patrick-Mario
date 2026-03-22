"""System-tray icon with play / pause / next / settings / quit controls."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

logger = logging.getLogger(__name__)


class LiveWallTray(QSystemTrayIcon):
    """Persistent system-tray icon for LiveWall."""

    def __init__(
        self,
        on_toggle_pause: Callable[[], None],
        on_next: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_toggle_pause = on_toggle_pause
        self._on_next = on_next
        self._on_settings = on_settings
        self._on_quit = on_quit

        self.setIcon(self._make_icon())
        self.setToolTip("LiveWall")
        self._build_menu()
        self.show()
        logger.info("System tray icon visible")

    # ------------------------------------------------------------------

    @staticmethod
    def _make_icon() -> QIcon:
        pm = QPixmap(32, 32)
        pm.fill(QColor(76, 175, 80))  # Material green
        return QIcon(pm)

    def _build_menu(self) -> None:
        menu = QMenu()

        self._pause_action: QAction = menu.addAction("Pause")  # type: ignore[assignment]
        self._pause_action.triggered.connect(self._handle_toggle)

        next_action: QAction = menu.addAction("Next Wallpaper")  # type: ignore[assignment]
        next_action.triggered.connect(self._on_next)

        menu.addSeparator()

        settings_action: QAction = menu.addAction("Settings…")  # type: ignore[assignment]
        settings_action.triggered.connect(self._on_settings)

        menu.addSeparator()

        quit_action: QAction = menu.addAction("Quit")  # type: ignore[assignment]
        quit_action.triggered.connect(self._on_quit)

        self.setContextMenu(menu)

    def _handle_toggle(self) -> None:
        self._on_toggle_pause()

    # ------------------------------------------------------------------
    # Public API for the app to update displayed state
    # ------------------------------------------------------------------

    def update_play_state(self, *, playing: bool) -> None:
        """Update the pause/resume menu label."""
        self._pause_action.setText("Pause" if playing else "Resume")
