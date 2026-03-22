"""Spin the mouse cursor in circles at screen center. Press Shift to stop."""

from __future__ import annotations

import math
import sys
import threading
import time

import pyautogui
from pynput import keyboard

_MARGIN: int = 10  # pixels reserved so circle stays on-screen


def circle_point(cx: int, cy: int, radius: int, angle: float) -> tuple[int, int]:
    """Return the (x, y) point on a circle at the given angle (radians)."""
    return cx + int(radius * math.cos(angle)), cy + int(radius * math.sin(angle))


def clamp_radius(radius: int, screen_w: int, screen_h: int) -> int:
    """Clamp *radius* so the full circle fits within the screen."""
    max_radius = min(screen_w, screen_h) // 2 - _MARGIN
    return max(1, min(radius, max_radius))


def spin_cursor(
    loops: int = 5,
    radius: int = 150,
    steps_per_loop: int = 60,
    delay: float = 0.008,
) -> None:
    """Move the cursor in *loops* circles around screen center.

    Args:
        loops: Number of full circles.
        radius: Circle radius in pixels.
        steps_per_loop: Points sampled per circle (higher = smoother).
        delay: Seconds between each step (lower = faster).
    """
    stop_event = threading.Event()

    def on_press(key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key in (keyboard.Key.shift, keyboard.Key.shift_r):
            stop_event.set()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    try:
        screen_w, screen_h = pyautogui.size()
        cx, cy = screen_w // 2, screen_h // 2
        radius = clamp_radius(radius, screen_w, screen_h)

        pyautogui.moveTo(cx, cy)

        if stop_event.is_set():
            print("\nShift pressed before start — aborting.")
            return

        for loop in range(loops):
            for step in range(steps_per_loop):
                if stop_event.is_set():
                    print("\nShift pressed — stopping.")
                    return
                angle = 2 * math.pi * step / steps_per_loop
                x, y = circle_point(cx, cy, radius, angle)
                pyautogui.moveTo(x, y, _pause=False)
                time.sleep(delay)

        print(f"Done — completed {loops} circles.")

    except pyautogui.FailSafeException:
        print("\nMouse moved to corner — failsafe triggered.")
    except KeyboardInterrupt:
        print("\nCtrl+C — stopping.")
    finally:
        listener.stop()


if __name__ == "__main__":
    pyautogui.FAILSAFE = True  # move mouse to corner as backup failsafe
    print("Spinning cursor… press Shift to stop.")
    spin_cursor()
    sys.exit(0)
