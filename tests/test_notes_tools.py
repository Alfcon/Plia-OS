from unittest.mock import patch, MagicMock


def test_add_note_stores_with_note_prefix():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import add_note
        result = add_note("pick up groceries")
    key, value = mock_store.remember.call_args[0]
    assert key.startswith("note_")
    assert value == "pick up groceries"
    assert "pick up groceries" in result


def test_list_notes_filters_by_prefix():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "note_20260616_120000", "value": "buy milk"},
        {"key": "name", "value": "Alice"},
        {"key": "note_20260616_120001", "value": "call dentist"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import list_notes
        result = list_notes()
    assert "buy milk" in result
    assert "call dentist" in result
    assert "Alice" not in result


def test_list_notes_empty():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [{"key": "name", "value": "Alice"}]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import list_notes
        result = list_notes()
    assert "No notes" in result


def test_clear_notes_deletes_all():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "note_20260616_120000", "value": "a"},
        {"key": "note_20260616_120001", "value": "b"},
        {"key": "name", "value": "Alice"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import clear_notes
        result = clear_notes()
    assert mock_store.forget.call_count == 2
    assert "2 notes" in result


def test_delete_note_by_text():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [
        {"key": "note_20260616_120000", "value": "buy milk"},
        {"key": "note_20260616_120001", "value": "call dentist"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import delete_note
        result = delete_note("milk")
    mock_store.forget.assert_called_once_with("note_20260616_120000")
    assert "buy milk" in result


def test_delete_note_not_found():
    mock_store = MagicMock()
    mock_store.list_all.return_value = [{"key": "note_x", "value": "buy milk"}]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import delete_note
        result = delete_note("coffee")
    mock_store.forget.assert_not_called()
    assert "coffee" in result


def test_clear_notes_empty():
    mock_store = MagicMock()
    mock_store.list_all.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.memory_tools import clear_notes
        result = clear_notes()
    mock_store.forget.assert_not_called()
    assert "No notes" in result
