import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _state(user_text):
    return {"messages": [{"role": "user", "content": user_text}], "tool_results": []}


@pytest.mark.asyncio
async def test_remember_triggers_graph_ingest():
    from agents import memory
    store = MagicMock()
    parsed = {"content": '{"op":"remember","key":"job","value":"Jane works at Acme"}'}
    with patch("agents.memory.call_llm", new=AsyncMock(return_value=parsed)), \
         patch("agents.memory.get_memory_store", return_value=store), \
         patch("agents.graph_memory.ingest_fact", return_value=1) as ingest:
        out = await memory.memory_node(_state("remember Jane works at Acme"))
    store.remember.assert_called_once_with("job", "Jane works at Acme")
    ingest.assert_called_once_with("Jane works at Acme")   # value, not key
    assert any("Remembered" in r for r in out["tool_results"])


@pytest.mark.asyncio
async def test_ingest_failure_does_not_break_remember():
    from agents import memory
    store = MagicMock()
    parsed = {"content": '{"op":"remember","key":"job","value":"Jane works at Acme"}'}
    with patch("agents.memory.call_llm", new=AsyncMock(return_value=parsed)), \
         patch("agents.memory.get_memory_store", return_value=store), \
         patch("agents.graph_memory.ingest_fact", side_effect=RuntimeError("boom")):
        out = await memory.memory_node(_state("remember Jane works at Acme"))
    store.remember.assert_called_once()                    # fact still stored
    assert any("Remembered" in r for r in out["tool_results"])


@pytest.mark.asyncio
async def test_recall_does_not_trigger_ingest():
    from agents import memory
    store = MagicMock()
    store.recall.return_value = ["something"]
    parsed = {"content": '{"op":"recall","key":"x","value":""}'}
    with patch("agents.memory.call_llm", new=AsyncMock(return_value=parsed)), \
         patch("agents.memory.get_memory_store", return_value=store), \
         patch("agents.graph_memory.ingest_fact") as ingest:
        await memory.memory_node(_state("what do you know"))
    ingest.assert_not_called()
