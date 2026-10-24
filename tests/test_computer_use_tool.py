import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_use_computer_delegates():
    with patch("agents.computer_use.run_computer_use", new_callable=AsyncMock, return_value="Goal: x\nSteps (1):\n…") as m:
        from modules.computer_use_tools import use_computer
        out = await use_computer("open settings", max_steps=5)
    m.assert_awaited_once_with("open settings", 5)
    assert "Goal" in out


def test_use_computer_always_guarded():
    from core.tool_guard import _is_guarded
    cfg = MagicMock()
    cfg.tool_guard_list = []
    with patch("core.config.get_config", return_value=cfg):
        assert _is_guarded("use_computer") is True
        assert _is_guarded("some_other_tool") is False
