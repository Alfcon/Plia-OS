import pytest
from unittest.mock import AsyncMock, patch
from agents.file import file_node


def _state(user_text: str, prior_results: list | None = None) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": prior_results or [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await file_node(_state("read my file"))
    assert update["active_agent"] == "file"
    assert "couldn't parse" in "\n".join(update["tool_results"]).lower()


@pytest.mark.asyncio
async def test_unknown_action_returns_fallback():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"action":"unknown","path":"~/f.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("do unknown file thing"))
    assert update["active_agent"] == "file"
    assert "couldn't parse" in "\n".join(update["tool_results"]).lower()


@pytest.mark.asyncio
async def test_action_read_calls_read_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.read_file", return_value="file contents") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"read","path":"~/notes.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("read ~/notes.txt"))
    mock_fn.assert_called_once_with("~/notes.txt", 0, 0)
    assert update["active_agent"] == "file"
    assert any(r.startswith("[file]") for r in update["tool_results"])
    assert "file contents" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_action_write_calls_write_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.write_file", return_value="Written 5 chars.") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"write","path":"~/out.txt","destination":null,"content":"hello","query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("write hello to ~/out.txt"))
    mock_fn.assert_called_once_with("~/out.txt", "hello")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_action_find_calls_find_files():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.find_files", return_value="/home/user/a.py") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"find","path":"~","destination":null,"content":null,"query":"*.py","start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("find all python files"))
    mock_fn.assert_called_once_with("*.py", "~")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_action_run_calls_run_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.run_file", return_value="output") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"run","path":"~/script.py","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":"--verbose"}'}
        update = await file_node(_state("run ~/script.py --verbose"))
    mock_fn.assert_called_once_with("~/script.py", "--verbose")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.read_file", return_value="contents"):
        mock_llm.return_value = {"content": '{"action":"read","path":"~/f.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        state = _state("read ~/f.txt")
        state["tool_results"] = ["[memory]\nprior"]
        update = await file_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nprior"
