"""Tests for livewall.app — application orchestrator with mocked subsystems."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_monitor_check_pauses_on_fullscreen() -> None:
    """When a fullscreen window is detected the player should auto-pause."""
    with (
        patch("livewall.app.has_fullscreen_window", return_value=True),
        patch("livewall.app.is_on_battery", return_value=False),
    ):
        app = _make_stub_app()
        app._user_paused = False
        app._auto_paused = False

        app._monitor_check()

        app._player.pause.assert_called_once()
        assert app._auto_paused is True


def test_monitor_check_resumes_when_no_fullscreen() -> None:
    with (
        patch("livewall.app.has_fullscreen_window", return_value=False),
        patch("livewall.app.is_on_battery", return_value=False),
    ):
        app = _make_stub_app()
        app._user_paused = False
        app._auto_paused = True

        app._monitor_check()

        app._player.resume.assert_called_once()
        assert app._auto_paused is False


def test_monitor_check_pauses_on_battery() -> None:
    with (
        patch("livewall.app.has_fullscreen_window", return_value=False),
        patch("livewall.app.is_on_battery", return_value=True),
    ):
        app = _make_stub_app()
        app._user_paused = False
        app._auto_paused = False

        app._monitor_check()

        app._player.pause.assert_called_once()
        assert app._auto_paused is True


def test_monitor_check_skipped_when_user_paused() -> None:
    with (
        patch("livewall.app.has_fullscreen_window", return_value=True),
        patch("livewall.app.is_on_battery", return_value=True),
    ):
        app = _make_stub_app()
        app._user_paused = True
        app._auto_paused = False

        app._monitor_check()

        app._player.pause.assert_not_called()


def test_toggle_pause_user() -> None:
    app = _make_stub_app()
    app._user_paused = False
    app._toggle_pause()
    assert app._user_paused is True
    app._player.pause.assert_called_once()
    app._tray.update_play_state.assert_called_with(playing=False)

    app._toggle_pause()
    assert app._user_paused is False
    app._player.resume.assert_called_once()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_stub_app() -> LiveWallApp:  # type: ignore[name-defined]  # noqa: F821
    """Create a LiveWallApp-like object without __init__ side-effects."""
    from livewall.app import LiveWallApp

    app = object.__new__(LiveWallApp)
    app._player = MagicMock()
    app._tray = MagicMock()
    app._widget = MagicMock()
    app._config = MagicMock()
    app._qt_app = MagicMock()
    app._lock_fd = None
    app._user_paused = False
    app._auto_paused = False
    return app
