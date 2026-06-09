import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.calendar import calendar_node
from agents.calendar_store import reset_calendar_store


@pytest.fixture(autouse=True)
def isolated_store():
    reset_calendar_store()
    with patch("agents.calendar.get_calendar_store") as mock_gcs:
        mock_store = MagicMock()
        mock_store.add_event.return_value = "abc123-uid"
        mock_store.list_events.return_value = ["2026-07-01 10:00: Team meeting (uid: abc123)"]
        mock_store.delete_event.return_value = True
        mock_gcs.return_value = mock_store
        yield mock_store
    reset_calendar_store()


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
async def test_calendar_node_add_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"add","title":"Team meeting","date":"2026-07-01","time":"10:00","duration":60}'}
        update = await calendar_node(_state("add a team meeting on July 1 at 10am"))
    isolated_store.add_event.assert_called_once_with("Team meeting", "2026-07-01", "10:00", 60)
    assert update["active_agent"] == "calendar"
    assert any("Team meeting" in r or "Added" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_calendar_node_list_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"list"}'}
        update = await calendar_node(_state("what events do I have"))
    isolated_store.list_events.assert_called_once()
    assert update["active_agent"] == "calendar"
    assert any("Team meeting" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_calendar_node_delete_calls_store(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"delete","uid":"abc123-uid"}'}
        update = await calendar_node(_state("delete event abc123"))
    isolated_store.delete_event.assert_called_once_with("abc123-uid")
    assert update["active_agent"] == "calendar"


@pytest.mark.asyncio
async def test_calendar_node_llm_error_falls_back_to_list(isolated_store):
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await calendar_node(_state("show my calendar"))
    isolated_store.list_events.assert_called_once()
    assert update["active_agent"] == "calendar"


@pytest.mark.asyncio
async def test_calendar_node_accumulates_tool_results(isolated_store):
    state = _state("list events")
    state["tool_results"] = ["[memory]\nexisting"]
    with patch("agents.calendar.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"op":"list"}'}
        update = await calendar_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nexisting"
