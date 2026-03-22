"""Battery / AC power detection via sysfs."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

POWER_SUPPLY_DIR = Path("/sys/class/power_supply")


def is_on_battery() -> bool:
    """Return True when the machine is running on battery power.

    Reads /sys/class/power_supply/*/type and /online.
    Returns False if sysfs is unreadable or no battery info exists (desktops).
    """
    if not POWER_SUPPLY_DIR.exists():
        return False
    try:
        for supply in POWER_SUPPLY_DIR.iterdir():
            type_file = supply / "type"
            if not type_file.exists():
                continue
            supply_type = type_file.read_text().strip()
            if supply_type == "Mains":
                online_file = supply / "online"
                if online_file.exists():
                    return online_file.read_text().strip() == "0"
    except OSError as exc:
        logger.warning("Failed to read power supply info: %s", exc)
    return False
