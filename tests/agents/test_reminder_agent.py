import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.reminder import reminder_node


def _state(user_text: str) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_creates_reminder_calls_store():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 42
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Take meds","fire_at":"2026-06-13T15:00:00+00:00"}'}
        update = await reminder_node(_state("remind me to take meds at 3pm"))
    mock_store.add_reminder.assert_called_once_with("Take meds", "2026-06-13T15:00:00+00:00")
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_confirmation_in_tool_results():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 7
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Walk the dog","fire_at":"2026-06-14T08:00:00+00:00"}'}
        update = await reminder_node(_state("remind me to walk the dog tomorrow at 8am"))
    result = "\n".join(update["tool_results"])
    assert "Walk the dog" in result
    assert "2026-06-14" in result


@pytest.mark.asyncio
async def test_llm_parse_error_returns_helpful_message():
    mock_store = MagicMock()
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": "not json at all"}
        update = await reminder_node(_state("remind me somehow"))
    mock_store.add_reminder.assert_not_called()
    result = "\n".join(update["tool_results"])
    assert "remind me to" in result.lower() or "couldn't" in result.lower()
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_missing_fields_returns_helpful_message():
    mock_store = MagicMock()
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":""}'}  # missing fire_at, empty message
        update = await reminder_node(_state("remind me"))
    mock_store.add_reminder.assert_not_called()
    assert update["active_agent"] == "reminder"


@pytest.mark.asyncio
async def test_preserves_existing_tool_results():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 1
    state = _state("remind me to call John at noon")
    state["tool_results"] = ["[memory]\nsome prior result"]
    with patch("agents.reminder.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.reminder.get_memory_store", return_value=mock_store):
        mock_llm.return_value = {"content": '{"message":"Call John","fire_at":"2026-06-13T12:00:00+00:00"}'}
        update = await reminder_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nsome prior result"
