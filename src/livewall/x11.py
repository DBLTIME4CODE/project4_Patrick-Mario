"""X11 helpers for window manipulation and fullscreen detection."""

from __future__ import annotations

import logging

from Xlib import X, Xatom  # type: ignore[import-untyped]
from Xlib import display as xdisplay  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def _open_display() -> xdisplay.Display:
    return xdisplay.Display()


def set_desktop_window_type(window_id: int) -> None:
    """Set _NET_WM_WINDOW_TYPE to DESKTOP for the given X11 window."""
    d = _open_display()
    try:
        window = d.create_resource_object("window", window_id)
        net_wm_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
        desktop_type = d.intern_atom("_NET_WM_WINDOW_TYPE_DESKTOP")
        window.change_property(net_wm_type, Xatom.ATOM, 32, [desktop_type])
        d.flush()
        logger.info("Set window %d to _NET_WM_WINDOW_TYPE_DESKTOP", window_id)
    finally:
        d.close()


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the default screen."""
    d = _open_display()
    try:
        screen = d.screen()
        return screen.width_in_pixels, screen.height_in_pixels
    finally:
        d.close()


def has_fullscreen_window() -> bool:
    """Check whether any client window has _NET_WM_STATE_FULLSCREEN."""
    d = _open_display()
    try:
        root = d.screen().root
        net_client_list = d.intern_atom("_NET_CLIENT_LIST")
        net_wm_state = d.intern_atom("_NET_WM_STATE")
        fullscreen_atom = d.intern_atom("_NET_WM_STATE_FULLSCREEN")

        client_list = root.get_full_property(net_client_list, X.AnyPropertyType)
        if client_list is None:
            return False

        for wid in client_list.value:
            try:
                win = d.create_resource_object("window", wid)
                state = win.get_full_property(net_wm_state, X.AnyPropertyType)
                if state is not None and fullscreen_atom in state.value:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fullscreen detection failed: %s", exc)
        return False
    finally:
        d.close()
