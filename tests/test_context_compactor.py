import pytest
from unittest.mock import AsyncMock, patch
from core.context_compactor import maybe_compact, _COMPACT_THRESHOLD, _KEEP_RECENT


def _msgs(n: int, role: str = "user") -> list[dict]:
    return [{"role": role, "content": f"msg {i}"} for i in range(n)]


@pytest.mark.asyncio
async def test_no_compact_under_threshold():
    msgs = _msgs(_COMPACT_THRESHOLD)
    result = await maybe_compact(msgs)
    assert result == msgs


@pytest.mark.asyncio
async def test_compact_triggered_over_threshold():
    msgs = _msgs(_COMPACT_THRESHOLD + 5)
    with patch("core.context_compactor._summarise", new=AsyncMock(return_value="summary text")) as mock_sum:
        result = await maybe_compact(msgs)
    mock_sum.assert_called_once()
    non_system = [m for m in result if m.get("role") != "system"]
    assert len(non_system) == _KEEP_RECENT


@pytest.mark.asyncio
async def test_compact_preserves_system_messages():
    sys_msg = {"role": "system", "content": "You are Plia."}
    user_msgs = _msgs(_COMPACT_THRESHOLD + 5)
    msgs = [sys_msg] + user_msgs
    with patch("core.context_compactor._summarise", new=AsyncMock(return_value="summary")):
        result = await maybe_compact(msgs)
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "You are Plia."


@pytest.mark.asyncio
async def test_compact_injects_summary_message():
    msgs = _msgs(_COMPACT_THRESHOLD + 5)
    with patch("core.context_compactor._summarise", new=AsyncMock(return_value="KEY FACTS")):
        result = await maybe_compact(msgs)
    summary_msgs = [m for m in result if "Earlier conversation summary" in m.get("content", "")]
    assert len(summary_msgs) == 1
    assert "KEY FACTS" in summary_msgs[0]["content"]


@pytest.mark.asyncio
async def test_compact_failure_returns_original():
    msgs = _msgs(_COMPACT_THRESHOLD + 5)
    with patch("core.context_compactor._summarise", new=AsyncMock(side_effect=RuntimeError("fail"))):
        result = await maybe_compact(msgs)
    assert result == msgs
