"""Tests for scripts/ping_google.py."""

from __future__ import annotations

import subprocess
import types
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mod() -> types.ModuleType:
    """Import ping_google as a module from scripts/."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "ping_google",
        pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ping_google.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- build_ping_command ----------------------------------------------------


class TestBuildPingCommand:
    def test_default(self, mod: types.ModuleType) -> None:
        cmd = mod.build_ping_command()
        assert cmd == ["ping", "-n", "10", "8.8.8.8"]

    def test_custom(self, mod: types.ModuleType) -> None:
        cmd = mod.build_ping_command(host="example.com", count=5)
        assert cmd == ["ping", "-n", "5", "example.com"]

    def test_returns_list(self, mod: types.ModuleType) -> None:
        """Command is a list, never a string — prevents shell injection."""
        cmd = mod.build_ping_command()
        assert isinstance(cmd, list)


# -- main ------------------------------------------------------------------


class TestMain:
    def test_success(self, mod: types.ModuleType) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch.object(subprocess, "Popen", return_value=mock_proc) as mock_popen:
            rc = mod.main()

        assert rc == 0
        mock_popen.assert_called_once()
        args = mock_popen.call_args
        assert args[0][0] == ["ping", "-n", "10", "8.8.8.8"]
        assert args[1]["creationflags"] == subprocess.CREATE_NEW_CONSOLE

    def test_file_not_found(self, mod: types.ModuleType) -> None:
        with patch.object(subprocess, "Popen", side_effect=FileNotFoundError):
            rc = mod.main()
        assert rc == 1

    def test_timeout_kills_process(self, mod: types.ModuleType) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="ping", timeout=30)

        with patch.object(subprocess, "Popen", return_value=mock_proc):
            rc = mod.main()

        assert rc == 1
        mock_proc.kill.assert_called_once()

    def test_nonzero_returncode(self, mod: types.ModuleType) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.wait.return_value = None

        with patch.object(subprocess, "Popen", return_value=mock_proc):
            rc = mod.main()

        assert rc == 1
