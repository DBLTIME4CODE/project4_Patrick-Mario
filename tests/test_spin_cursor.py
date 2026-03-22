"""Tests for spin_cursor module — pure-function tests + integration."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

from myproject.spin_cursor import _MARGIN, circle_point, clamp_radius, spin_cursor

# -- circle_point ----------------------------------------------------------


class TestCirclePoint:
    def test_angle_0(self) -> None:
        """0 rad -> point directly to the right."""
        assert circle_point(100, 100, 50, 0.0) == (150, 100)

    def test_angle_half_pi(self) -> None:
        """pi/2 -> point directly below (screen coords)."""
        x, y = circle_point(100, 100, 50, math.pi / 2)
        assert x == 100
        assert y == 150

    def test_angle_pi(self) -> None:
        """pi -> point directly to the left."""
        x, y = circle_point(100, 100, 50, math.pi)
        assert x == 50
        assert y == 100

    def test_angle_three_half_pi(self) -> None:
        """3pi/2 -> point directly above."""
        x, y = circle_point(100, 100, 50, 3 * math.pi / 2)
        assert x == 100
        assert y == 50

    def test_zero_radius(self) -> None:
        """Edge: zero radius collapses to center."""
        assert circle_point(300, 200, 0, 1.23) == (300, 200)


# -- clamp_radius ----------------------------------------------------------


class TestClampRadius:
    def test_fits(self) -> None:
        """Radius smaller than half the smallest dimension stays unchanged."""
        assert clamp_radius(100, 1920, 1080) == 100

    def test_too_large(self) -> None:
        """Radius bigger than half the smallest dimension gets clamped."""
        expected = min(1920, 1080) // 2 - _MARGIN
        assert clamp_radius(9999, 1920, 1080) == expected

    def test_tiny_screen(self) -> None:
        """On an absurdly small screen, radius clamps to 1."""
        assert clamp_radius(100, 20, 20) == 1

    def test_exact_boundary(self) -> None:
        """Radius exactly at max allowed stays unchanged."""
        max_r = min(800, 600) // 2 - _MARGIN
        assert clamp_radius(max_r, 800, 600) == max_r


# -- spin_cursor integration -----------------------------------------------


class TestSpinCursorIntegration:
    @patch("myproject.spin_cursor.keyboard.Listener")
    @patch("myproject.spin_cursor.pyautogui")
    def test_early_stop(self, mock_pyautogui: MagicMock, mock_listener_cls: MagicMock) -> None:
        """If stop_event is set before spinning, cursor moves to center only."""
        mock_pyautogui.size.return_value = (1920, 1080)
        mock_pyautogui.FailSafeException = Exception

        def start_side_effect() -> None:
            on_press_cb = mock_listener_cls.call_args[1]["on_press"]
            from pynput import keyboard as kb

            on_press_cb(kb.Key.shift)

        mock_listener = MagicMock()
        mock_listener.start.side_effect = start_side_effect
        mock_listener_cls.return_value = mock_listener

        spin_cursor(loops=5)

        # moveTo called once (to center), no circle movement
        mock_pyautogui.moveTo.assert_called_once_with(960, 540)
        mock_listener.stop.assert_called_once()
