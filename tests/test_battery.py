"""Battery status for the top bar: percentage, runtime left, and time to full."""
from types import SimpleNamespace
from unittest.mock import patch

import core.battery as battery


def _bat(percent=50.0, plugged=False, secsleft=-1):
    return SimpleNamespace(percent=percent, power_plugged=plugged, secsleft=secsleft)


def _sysfs(tmp_path, status="Charging", **files):
    base = tmp_path / "BAT0"
    base.mkdir(exist_ok=True)
    (base / "status").write_text(status)
    for name, value in files.items():
        (base / name).write_text(str(value))
    return str(tmp_path)


# ---------------------------------------------------------------------------
# No battery / non-laptop
# ---------------------------------------------------------------------------

def test_no_battery_returns_none():
    with patch("psutil.sensors_battery", return_value=None):
        assert battery.battery_status() is None


def test_psutil_unavailable_returns_none():
    with patch("psutil.sensors_battery", side_effect=AttributeError):
        assert battery.battery_status() is None


# ---------------------------------------------------------------------------
# Discharging → runtime left
# ---------------------------------------------------------------------------

def test_discharging_reports_seconds_left(tmp_path):
    with patch("psutil.sensors_battery", return_value=_bat(percent=42.64, secsleft=5400)):
        info = battery.battery_status(_sysfs(tmp_path, status="Discharging"))
    assert info["percent"] == 42.6
    assert info["plugged"] is False
    assert info["status"] == "Discharging"
    assert info["secs_left"] == 5400
    assert info["secs_to_full"] is None


def test_unknown_and_unlimited_secsleft_are_none(tmp_path):
    for sentinel in (-1, -2):  # psutil POWER_TIME_UNKNOWN / POWER_TIME_UNLIMITED
        with patch("psutil.sensors_battery", return_value=_bat(secsleft=sentinel)):
            info = battery.battery_status(_sysfs(tmp_path, status="Discharging"))
        assert info["secs_left"] is None


# ---------------------------------------------------------------------------
# Charging → time to full (psutil reports no runtime estimate here)
# ---------------------------------------------------------------------------

def test_charging_derives_time_to_full_from_charge_now(tmp_path):
    # 1607/4360 mAh charged at 2763 mA → ~3590 s to full.
    d = _sysfs(tmp_path, charge_now=1607000, charge_full=4360000, current_now=2763000)
    with patch("psutil.sensors_battery", return_value=_bat(percent=37.0, plugged=True, secsleft=-2)):
        info = battery.battery_status(d)
    assert info["plugged"] is True
    assert info["status"] == "Charging"
    assert info["secs_left"] is None
    assert 3500 <= info["secs_to_full"] <= 3650


def test_charging_prefers_kernel_time_to_full(tmp_path):
    d = _sysfs(tmp_path, time_to_full_now=7_200_000_000, charge_now=1, charge_full=2, current_now=1)
    with patch("psutil.sensors_battery", return_value=_bat(plugged=True, secsleft=-2)):
        info = battery.battery_status(d)
    assert info["secs_to_full"] == 7200


def test_charging_uses_energy_when_charge_absent(tmp_path):
    d = _sysfs(tmp_path, energy_now=10_000_000, energy_full=40_000_000, power_now=10_000_000)
    with patch("psutil.sensors_battery", return_value=_bat(plugged=True, secsleft=-2)):
        info = battery.battery_status(d)
    assert info["secs_to_full"] == int(30_000_000 / 10_000_000 * 3600)


def test_charging_without_estimate_is_none(tmp_path):
    d = _sysfs(tmp_path, status="Not charging")
    with patch("psutil.sensors_battery", return_value=_bat(plugged=True, secsleft=-2)):
        info = battery.battery_status(d)
    assert info["secs_to_full"] is None
    assert info["status"] == "Not charging"


def test_full_battery_has_no_time_to_full(tmp_path):
    d = _sysfs(tmp_path, status="Full", charge_now=4360000, charge_full=4360000, current_now=0)
    with patch("psutil.sensors_battery", return_value=_bat(percent=100.0, plugged=True, secsleft=-2)):
        info = battery.battery_status(d)
    assert info["secs_to_full"] is None
    assert info["status"] == "Full"


def test_no_sysfs_entry_still_reports_percentage():
    with patch("psutil.sensors_battery", return_value=_bat(percent=88.0, plugged=True, secsleft=-2)):
        info = battery.battery_status("/nonexistent/power_supply")
    assert info["percent"] == 88.0
    assert info["status"] == "Charging"
    assert info["secs_to_full"] is None
