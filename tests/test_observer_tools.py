from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def _make_obs(running=True, profile="User coding.", last_capture="2026-01-01T00:00:00",
              last_profile="2026-01-01T00:05:00"):
    obs = MagicMock()
    obs.is_running.return_value = running
    obs.get_profile.return_value = profile
    obs.last_capture_ts.return_value = last_capture
    obs.last_profile_ts.return_value = last_profile
    return obs


def test_observer_status_running():
    obs = _make_obs(running=True)
    with patch("core.observer.get_observer", return_value=obs):
        from modules.observer_tools import observer_status
        result = observer_status()
    assert "running" in result.lower()
    assert "User coding." in result


def test_observer_status_stopped():
    obs = _make_obs(running=False, profile="")
    with patch("core.observer.get_observer", return_value=obs):
        from modules.observer_tools import observer_status
        result = observer_status()
    assert "stopped" in result.lower() or "not running" in result.lower()


def test_enable_observer_updates_config():
    obs = _make_obs(running=False)
    obs.start = AsyncMock()
    with patch("core.observer.get_observer", return_value=obs), \
         patch("core.config.update_config") as mock_update:
        from modules.observer_tools import enable_observer
        result = enable_observer()
    mock_update.assert_called_with(observer_enabled=True)
    assert "enabled" in result.lower()


def test_disable_observer_updates_config():
    obs = _make_obs(running=True)
    obs.stop = AsyncMock()
    with patch("core.observer.get_observer", return_value=obs), \
         patch("core.config.update_config") as mock_update:
        from modules.observer_tools import disable_observer
        result = disable_observer()
    mock_update.assert_called_with(observer_enabled=False)
    assert "disabled" in result.lower()
