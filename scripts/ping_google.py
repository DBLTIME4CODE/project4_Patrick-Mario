"""Ping 8.8.8.8 for ~10 seconds in a visible cmd window."""

from __future__ import annotations

import subprocess
import sys

_HOST = "8.8.8.8"
_COUNT = 10
_SAFETY_TIMEOUT = 30  # generous fallback; -n 10 should finish in ~10s


def build_ping_command(host: str = _HOST, count: int = _COUNT) -> list[str]:
    """Return the ping command as a list of args (Windows)."""
    return ["ping", "-n", str(count), host]


def main() -> int:
    """Launch ping in a new console window and wait for it to finish."""
    cmd = build_ping_command()
    try:
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        proc.wait(timeout=_SAFETY_TIMEOUT)
    except FileNotFoundError:
        print("Error: 'ping' not found on this system.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return 1
    return proc.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
