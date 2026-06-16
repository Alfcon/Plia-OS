import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


def test_save_memory_stores_fact():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import save_memory
        result = save_memory("name", "Alice")
    mock_store.remember.assert_called_once_with("name", "Alice")
    assert "name" in result
    assert "Alice" in result


def test_save_memory_overwrites_existing():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import save_memory
        save_memory("city", "Berlin")
        save_memory("city", "Paris")
    assert mock_store.remember.call_count == 2
    assert mock_store.remember.call_args_list[1][0] == ("city", "Paris")


def test_list_memories_empty():
    mock_store = MagicMock()
    mock_store.list_all.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import list_memories
        result = list_memories()
    assert "No memories" in result


def test_list_memories_shows_facts():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "name", "value": "Alice"},
        {"key": "city", "value": "Berlin"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import list_memories
        result = list_memories()
    assert "name: Alice" in result
    assert "city: Berlin" in result


def test_forget_memory_deletes():
    mock_store = MagicMock()
    mock_store.get_fact.return_value = "Alice"
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import forget_memory
        result = forget_memory("name")
    mock_store.forget.assert_called_once_with("name")
    assert "name" in result


def test_forget_memory_not_found():
    mock_store = MagicMock()
    mock_store.get_fact.return_value = None
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import forget_memory
        result = forget_memory("unknown")
    mock_store.forget.assert_not_called()
    assert "unknown" in result


def test_search_memories_returns_results():
    mock_store = MagicMock()
    mock_store.recall.return_value = ["user: my dog is named Rex", "I love hiking"]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import search_memories
        result = search_memories("dog")
    mock_store.recall.assert_called_once_with("dog")
    assert "Rex" in result
    assert "hiking" in result


def test_search_memories_empty():
    mock_store = MagicMock()
    mock_store.recall.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import search_memories
        result = search_memories("nothing")
    assert "No relevant" in result


def test_clear_conversation_clears_db_and_emits_event():
    mock_store = MagicMock()
    mock_emit = AsyncMock()

    with patch("agents.memory_store.get_memory_store", return_value=mock_store), \
         patch("core.events.emit", mock_emit):
        # Need a running event loop for create_task
        async def _run():
            from modules.example_module import clear_conversation
            result = clear_conversation()
            # drain scheduled tasks
            await asyncio.sleep(0)
            return result
        result = asyncio.run(_run())

    mock_store.clear_history.assert_called_once()
    mock_emit.assert_awaited_once()
    payload = mock_emit.call_args
    assert payload.args[0] == "clear_history"
    assert "cleared" in result.lower()
