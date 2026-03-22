"""Tests for livewall.config — load / save / defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from livewall.config import LiveWallConfig, load_config, save_config


def test_default_config_values() -> None:
    cfg = LiveWallConfig()
    assert cfg.wallpaper_path == ""
    assert cfg.volume == 0
    assert cfg.loop is True
    assert cfg.mute is True
    assert cfg.autostart is False


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_dir = tmp_path / "livewall"
    cfg_file = cfg_dir / "config.json"
    monkeypatch.setattr("livewall.config.CONFIG_DIR", cfg_dir)
    monkeypatch.setattr("livewall.config.CONFIG_PATH", cfg_file)

    original = LiveWallConfig(
        wallpaper_path="/tmp/test.mp4",
        wallpaper_dir="/tmp",
        volume=42,
        loop=False,
        autostart=True,
        mute=False,
    )
    save_config(original)

    loaded = load_config()
    assert loaded.wallpaper_path == original.wallpaper_path
    assert loaded.volume == original.volume
    assert loaded.loop == original.loop
    assert loaded.autostart == original.autostart
    assert loaded.mute == original.mute


def test_load_missing_config_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("livewall.config.CONFIG_PATH", tmp_path / "nope.json")
    cfg = load_config()
    assert cfg == LiveWallConfig()


def test_load_corrupt_config_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_file = tmp_path / "config.json"
    bad_file.write_text("NOT JSON", encoding="utf-8")
    monkeypatch.setattr("livewall.config.CONFIG_PATH", bad_file)
    cfg = load_config()
    assert cfg == LiveWallConfig()


def test_load_ignores_unknown_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"wallpaper_path": "/v.mp4", "unknown_key": 99}),
        encoding="utf-8",
    )
    monkeypatch.setattr("livewall.config.CONFIG_PATH", cfg_file)
    cfg = load_config()
    assert cfg.wallpaper_path == "/v.mp4"
