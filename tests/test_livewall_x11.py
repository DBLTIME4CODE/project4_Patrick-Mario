"""Tests for livewall.x11 — mocked python-xlib interactions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_display(
    screen_w: int = 1920,
    screen_h: int = 1080,
    client_wids: list[int] | None = None,
    fullscreen_wids: set[int] | None = None,
) -> MagicMock:
    """Build a mock Xlib Display with configurable properties."""
    d = MagicMock()
    screen = MagicMock()
    screen.width_in_pixels = screen_w
    screen.height_in_pixels = screen_h
    d.screen.return_value = screen

    # intern_atom returns stable fake ints for each atom name
    atom_map: dict[str, int] = {}
    _counter = [1000]

    def _intern(name: str) -> int:
        if name not in atom_map:
            atom_map[name] = _counter[0]
            _counter[0] += 1
        return atom_map[name]

    d.intern_atom.side_effect = _intern

    # Root window with _NET_CLIENT_LIST
    root = MagicMock()
    if client_wids is not None:
        prop = MagicMock()
        prop.value = client_wids
        root.get_full_property.return_value = prop
    else:
        root.get_full_property.return_value = None
    screen.root = root

    # Per-window state
    fullscreen_wids = fullscreen_wids or set()
    fs_atom: int | None = None

    def _make_window(wid: int) -> MagicMock:
        nonlocal fs_atom
        if fs_atom is None:
            fs_atom = _intern("_NET_WM_STATE_FULLSCREEN")
        win = MagicMock()
        if wid in fullscreen_wids:
            state_prop = MagicMock()
            state_prop.value = [fs_atom]
            win.get_full_property.return_value = state_prop
        else:
            state_prop = MagicMock()
            state_prop.value = []
            win.get_full_property.return_value = state_prop
        return win

    d.create_resource_object.side_effect = lambda _kind, wid: _make_window(wid)
    return d


# ------------------------------------------------------------------
# set_desktop_window_type
# ------------------------------------------------------------------


@patch("livewall.x11._open_display")
def test_set_desktop_window_type(mock_open: MagicMock) -> None:
    d = _mock_display()
    mock_open.return_value = d

    from livewall.x11 import set_desktop_window_type

    set_desktop_window_type(42)

    d.create_resource_object.assert_called_once_with("window", 42)
    d.flush.assert_called_once()
    d.close.assert_called_once()


# ------------------------------------------------------------------
# get_screen_size
# ------------------------------------------------------------------


@patch("livewall.x11._open_display")
def test_get_screen_size(mock_open: MagicMock) -> None:
    d = _mock_display(screen_w=2560, screen_h=1440)
    mock_open.return_value = d

    from livewall.x11 import get_screen_size

    w, h = get_screen_size()
    assert (w, h) == (2560, 1440)
    d.close.assert_called_once()


# ------------------------------------------------------------------
# has_fullscreen_window
# ------------------------------------------------------------------


@patch("livewall.x11._open_display")
def test_has_fullscreen_true(mock_open: MagicMock) -> None:
    d = _mock_display(client_wids=[1, 2, 3], fullscreen_wids={2})
    mock_open.return_value = d

    from livewall.x11 import has_fullscreen_window

    assert has_fullscreen_window() is True


@patch("livewall.x11._open_display")
def test_has_fullscreen_false(mock_open: MagicMock) -> None:
    d = _mock_display(client_wids=[1, 2, 3], fullscreen_wids=set())
    mock_open.return_value = d

    from livewall.x11 import has_fullscreen_window

    assert has_fullscreen_window() is False


@patch("livewall.x11._open_display")
def test_has_fullscreen_no_clients(mock_open: MagicMock) -> None:
    d = _mock_display(client_wids=None)
    mock_open.return_value = d

    from livewall.x11 import has_fullscreen_window

    assert has_fullscreen_window() is False
