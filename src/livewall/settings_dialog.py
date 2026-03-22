"""Settings dialog with wallpaper browser and thumbnail preview."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from livewall.config import LiveWallConfig

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Modal dialog for editing LiveWall preferences."""

    def __init__(self, config: LiveWallConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LiveWall Settings")
        self.setMinimumWidth(480)
        self._config = config
        self._thumb_path: str | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- wallpaper path row ----
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Wallpaper:"))
        self._path_edit = QLineEdit(self._config.wallpaper_path)
        self._path_edit.setReadOnly(True)
        path_row.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # ---- preview ----
        self._preview = QLabel("No preview")
        self._preview.setFixedSize(320, 180)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background:#222;border:1px solid #555;color:#aaa;")
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignCenter)

        # ---- volume ----
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Volume:"))
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._config.volume)
        self._volume_label = QLabel(str(self._config.volume))
        self._volume_slider.valueChanged.connect(lambda v: self._volume_label.setText(str(v)))
        vol_row.addWidget(self._volume_slider, stretch=1)
        vol_row.addWidget(self._volume_label)
        layout.addLayout(vol_row)

        # ---- checkboxes ----
        self._mute_cb = QCheckBox("Mute audio")
        self._mute_cb.setChecked(self._config.mute)
        layout.addWidget(self._mute_cb)

        self._loop_cb = QCheckBox("Loop wallpaper")
        self._loop_cb.setChecked(self._config.loop)
        layout.addWidget(self._loop_cb)

        self._autostart_cb = QCheckBox("Start on login")
        self._autostart_cb.setChecked(self._config.autostart)
        layout.addWidget(self._autostart_cb)

        # ---- buttons ----
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # load initial preview
        if self._config.wallpaper_path:
            self._update_preview(self._config.wallpaper_path)

    # ------------------------------------------------------------------
    # File browsing & preview
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        start_dir = self._config.wallpaper_dir
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Wallpaper",
            start_dir,
            "Videos (*.mp4 *.webm *.mkv *.gif);;All Files (*)",
        )
        if path:
            self._path_edit.setText(path)
            self._update_preview(path)

    def _update_preview(self, path: str) -> None:
        # GIF / image — Qt can handle directly
        if path.lower().endswith(".gif"):
            pm = QPixmap(path)
            if not pm.isNull():
                self._preview.setPixmap(pm.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatio))
                return

        # Video — try extracting a frame with ffmpeg
        thumb = self._extract_thumbnail(path)
        if thumb:
            pm = QPixmap(thumb)
            if not pm.isNull():
                self._preview.setPixmap(pm.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatio))
                return

        # Fallback: filename only
        name = Path(path).name
        self._preview.setText(f"\U0001f3ac {name}")

    @staticmethod
    def _extract_thumbnail(video_path: str) -> str | None:
        """Use ffmpeg (if available) to grab a frame at t=1 s."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp_name = tmp.name
            tmp.close()
            result = subprocess.run(  # noqa: S603
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-ss",
                    "00:00:01",
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    tmp_name,
                ],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return tmp_name
            Path(tmp_name).unlink(missing_ok=True)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def get_config(self) -> LiveWallConfig:
        """Return a new config reflecting the current dialog state."""
        wp = self._path_edit.text()
        return LiveWallConfig(
            wallpaper_path=wp,
            wallpaper_dir=str(Path(wp).parent) if wp else self._config.wallpaper_dir,
            volume=self._volume_slider.value(),
            loop=self._loop_cb.isChecked(),
            autostart=self._autostart_cb.isChecked(),
            mute=self._mute_cb.isChecked(),
        )
