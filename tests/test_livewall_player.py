"""Tests for livewall.player — mpv wrapper with mocked backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_mpv_module() -> MagicMock:
    """Provide a mock ``mpv`` module with a fake MPV class."""
    mock_mod = MagicMock()
    mock_instance = MagicMock()
    mock_mod.MPV.return_value = mock_instance
    return mock_mod


@pytest.fixture()
def player(mock_mpv_module: MagicMock) -> Any:
    with patch.dict("sys.modules", {"mpv": mock_mpv_module}):
        import importlib

        import livewall.player as mod

        importlib.reload(mod)
        return mod.WallpaperPlayer(wid=12345)


def test_init_creates_mpv(mock_mpv_module: MagicMock, player: Any) -> None:
    mock_mpv_module.MPV.assert_called_once()


def test_play_calls_mpv(mock_mpv_module: MagicMock, player: Any, tmp_path: Path) -> None:
    video = tmp_path / "wall.mp4"
    video.write_bytes(b"\x00")
    player.play(str(video))
    mock_mpv_module.MPV.return_value.play.assert_called_once_with(str(video))


def test_play_missing_file_does_not_crash(player: Any, tmp_path: Path) -> None:
    player.play(str(tmp_path / "nope.mp4"))


def test_pause_resume(mock_mpv_module: MagicMock, player: Any) -> None:
    player.pause()
    assert player.is_paused
    player.resume()
    assert not player.is_paused


def test_toggle_pause(mock_mpv_module: MagicMock, player: Any) -> None:
    player.toggle_pause()
    assert player.is_paused
    player.toggle_pause()
    assert not player.is_paused


def test_set_volume_clamped(mock_mpv_module: MagicMock, player: Any) -> None:
    instance = mock_mpv_module.MPV.return_value
    player.set_volume(150)
    assert instance.volume == 100
    player.set_volume(-5)
    assert instance.volume == 0


def test_stop_terminates(mock_mpv_module: MagicMock, player: Any) -> None:
    player.stop()
    mock_mpv_module.MPV.return_value.terminate.assert_called_once()
