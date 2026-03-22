"""Tests for livewall.autostart — .desktop file creation / removal."""

from __future__ import annotations

from pathlib import Path

import pytest

import livewall.autostart as autostart_mod
from livewall.autostart import install_autostart, remove_autostart


def test_install_creates_desktop_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adir = tmp_path / "autostart"
    dfile = adir / "livewall.desktop"
    monkeypatch.setattr(autostart_mod, "AUTOSTART_DIR", adir)
    monkeypatch.setattr(autostart_mod, "DESKTOP_FILE", dfile)

    install_autostart()

    assert dfile.exists()
    content = dfile.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Exec=livewall --start" in content


def test_remove_deletes_desktop_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adir = tmp_path / "autostart"
    dfile = adir / "livewall.desktop"
    adir.mkdir()
    dfile.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(autostart_mod, "AUTOSTART_DIR", adir)
    monkeypatch.setattr(autostart_mod, "DESKTOP_FILE", dfile)

    remove_autostart()

    assert not dfile.exists()


def test_remove_missing_file_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dfile = tmp_path / "livewall.desktop"
    monkeypatch.setattr(autostart_mod, "DESKTOP_FILE", dfile)
    remove_autostart()  # should not raise
