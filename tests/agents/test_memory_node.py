import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.memory import memory_node
from agents.memory_store import reset_memory_store


@pytest.fixture(autouse=True)
def isolated_store():
    reset_memory_store()
    with patch("agents.memory.get_memory_store") as mock_gsm:
        mock_store = MagicMock()
        mock_store.recall.return_value = ["user: my dog is named Rex"]
        mock_store.get_fact.return_value = None
        mock_gsm.return_value = mock_store
        yield mock_store
    reset_memory_store()


def _state(user_text):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_recall_returns_context(isolated_store):
    isolated_store.recall.return_value = ["user: my dog is Rex"]
    update = await memory_node(_state("what is my dog's name"))
    assert update["active_agent"] == "memory"
    assert "Rex" in update.get("memory_context", "") or any("Rex" in r for r in update.get("tool_results", []))


@pytest.mark.asyncio
async def test_remember_calls_store(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"remember","key":"user.dog","value":"Rex"}'}
        update = await memory_node(_state("remember my dog is named Rex"))
    isolated_store.remember.assert_called_once_with("user.dog", "Rex")
    assert update["active_agent"] == "memory"


@pytest.mark.asyncio
async def test_forget_calls_store(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"forget","key":"user.dog","value":""}'}
        update = await memory_node(_state("forget my dog's name"))
    isolated_store.forget.assert_called_once_with("user.dog")
    assert update["active_agent"] == "memory"


@pytest.mark.asyncio
async def test_llm_parse_error_falls_back_to_recall(isolated_store):
    with patch("agents.memory.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await memory_node(_state("what do you remember about me"))
    assert update["active_agent"] == "memory"
    assert isinstance(update.get("tool_results"), list)
