from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


def test_proactive_config_defaults():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.proactive_enabled is False
    assert cfg.proactive_check_interval == 60
    assert cfg.proactive_distraction_threshold == 20
    assert cfg.proactive_checkin_interval == 120
    assert cfg.proactive_quiet_hours_start == 0
    assert cfg.proactive_quiet_hours_end == 7
