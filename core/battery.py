"""Battery status for the dashboard top bar.

psutil supplies the charge percentage and — while discharging — the seconds of
runtime left. Linux power-supply sysfs is consulted only while charging, where
psutil reports ``POWER_TIME_UNLIMITED``, to derive an estimate of time to full.
"""
from __future__ import annotations

import glob
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_POWER_SUPPLY_DIR = "/sys/class/power_supply"


def _int_from(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _str_from(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _charge_estimate(base: Path) -> int | None:
    """Seconds until full: the kernel's estimate if present, else charge/rate."""
    micros = _int_from(base / "time_to_full_now")
    if micros and micros > 0:
        return micros // 1_000_000
    # charge_* is in µAh with current_now in µA; energy_* is µWh with power_now µW.
    for now_name, full_name, rate_name in (
        ("charge_now", "charge_full", "current_now"),
        ("energy_now", "energy_full", "power_now"),
    ):
        now = _int_from(base / now_name)
        full = _int_from(base / full_name)
        rate = _int_from(base / rate_name)
        if now is None or full is None or rate is None or rate <= 0:
            continue
        return int((full - now) / rate * 3600) if full > now else None
    return None


def battery_status(power_supply_dir: str | None = None) -> dict | None:
    """Battery percentage and time estimate, or None when there is no battery.

    Keys: ``percent``, ``plugged``, ``status``, ``secs_left`` (discharging) and
    ``secs_to_full`` (charging). Both time fields are seconds, or None when the
    estimate is unavailable.
    """
    directory = power_supply_dir or _POWER_SUPPLY_DIR
    try:
        import psutil
        bat = psutil.sensors_battery()
    except Exception:
        bat = None
    if bat is None:
        return None

    plugged = bool(getattr(bat, "power_plugged", False))
    status = "Charging" if plugged else "Discharging"
    secs_left: int | None = None
    secs_to_full: int | None = None

    for candidate in sorted(glob.glob(os.path.join(directory, "BAT*"))):
        base = Path(candidate)
        status = _str_from(base / "status") or status
        if plugged:
            secs_to_full = _charge_estimate(base)
        break

    if not plugged:
        secs = getattr(bat, "secsleft", None)
        # psutil uses -1 (unknown) / -2 (unlimited, i.e. on AC) for no estimate.
        if isinstance(secs, int) and secs >= 0:
            secs_left = secs

    percent = getattr(bat, "percent", None)
    return {
        "percent": round(percent, 1) if percent is not None else None,
        "plugged": plugged,
        "status": status,
        "secs_left": secs_left,
        "secs_to_full": secs_to_full,
    }
