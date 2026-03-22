"""Tests for livewall.power — battery detection via sysfs mocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from livewall.power import is_on_battery


def _make_supply(base: Path, name: str, stype: str, online: str | None = None) -> None:
    d = base / name
    d.mkdir(parents=True)
    (d / "type").write_text(stype, encoding="utf-8")
    if online is not None:
        (d / "online").write_text(online, encoding="utf-8")


def test_on_ac_power(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ps = tmp_path / "power_supply"
    ps.mkdir()
    _make_supply(ps, "AC0", "Mains", online="1")
    monkeypatch.setattr("livewall.power.POWER_SUPPLY_DIR", ps)
    assert is_on_battery() is False


def test_on_battery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ps = tmp_path / "power_supply"
    ps.mkdir()
    _make_supply(ps, "AC0", "Mains", online="0")
    monkeypatch.setattr("livewall.power.POWER_SUPPLY_DIR", ps)
    assert is_on_battery() is True


def test_no_power_supply_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("livewall.power.POWER_SUPPLY_DIR", tmp_path / "nonexistent")
    assert is_on_battery() is False


def test_battery_type_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ps = tmp_path / "power_supply"
    ps.mkdir()
    _make_supply(ps, "BAT0", "Battery")  # no Mains → not "on battery"
    monkeypatch.setattr("livewall.power.POWER_SUPPLY_DIR", ps)
    assert is_on_battery() is False
