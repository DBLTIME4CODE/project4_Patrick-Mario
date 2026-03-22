"""Tests for livewall.cli — argument parsing and sub-commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_set_wallpaper_updates_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_dir = tmp_path / "livewall"
    cfg_file = cfg_dir / "config.json"
    monkeypatch.setattr("livewall.config.CONFIG_DIR", cfg_dir)
    monkeypatch.setattr("livewall.config.CONFIG_PATH", cfg_file)
    # Also patch the cli module's import path
    monkeypatch.setattr("livewall.cli.CONFIG_DIR", cfg_dir)

    video = tmp_path / "cool.mp4"
    video.write_bytes(b"\x00")

    from livewall.cli import _set_wallpaper

    _set_wallpaper(str(video))

    assert cfg_file.exists()
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["wallpaper_path"] == str(video.resolve())


def test_set_wallpaper_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        from livewall.cli import _set_wallpaper

        _set_wallpaper(str(tmp_path / "nope.mp4"))


def test_stop_no_pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("livewall.cli.PID_FILE", tmp_path / "livewall.pid")
    with pytest.raises(SystemExit):
        from livewall.cli import _stop_running

        _stop_running()


def test_argument_parsing_default_is_start() -> None:
    """No arguments → default start action (not stop, not set)."""
    import argparse

    from livewall.cli import main

    with patch("livewall.cli._start") as mock_start:
        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(start=False, stop=False, set=None),
        ):
            main()
    mock_start.assert_called_once()


def test_argument_parsing_stop() -> None:
    import argparse

    from livewall.cli import main

    with patch("livewall.cli._stop_running") as mock_stop:
        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(start=False, stop=True, set=None),
        ):
            main()
    mock_stop.assert_called_once()
