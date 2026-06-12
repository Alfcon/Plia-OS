import pytest
from unittest.mock import AsyncMock, patch
from agents.code import code_node


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
async def test_code_node_runs_python_and_returns_output():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="42\n") as mock_py:
        mock_llm.return_value = {"content": '{"language":"python","code":"print(6*7)"}'}
        update = await code_node(_state("run this: print(6*7)"))
    mock_py.assert_called_once_with("print(6*7)")
    assert update["active_agent"] == "code"
    assert any("42" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_code_node_runs_shell_and_returns_output():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_shell", return_value="hello\n") as mock_sh:
        mock_llm.return_value = {"content": '{"language":"shell","code":"echo hello"}'}
        update = await code_node(_state("run shell: echo hello"))
    mock_sh.assert_called_once_with("echo hello")
    assert update["active_agent"] == "code"
    assert any("hello" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_code_node_defaults_to_python_on_unknown_language():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="ok\n") as mock_py:
        mock_llm.return_value = {"content": '{"language":"ruby","code":"puts 42"}'}
        update = await code_node(_state("run puts 42"))
    mock_py.assert_called_once_with("puts 42")
    assert update["active_agent"] == "code"


@pytest.mark.asyncio
async def test_code_node_llm_parse_error_returns_error_not_raw_input():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python") as mock_py:
        mock_llm.return_value = {"content": "not json at all"}
        update = await code_node(_state("print('hello')"))
    mock_py.assert_not_called()
    assert update["active_agent"] == "code"
    assert any("Could not extract" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_code_node_accumulates_tool_results():
    existing = ["[memory]\nprevious context"]
    state = _state("run print(1)")
    state["tool_results"] = existing
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="1\n"):
        mock_llm.return_value = {"content": '{"language":"python","code":"print(1)"}'}
        update = await code_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == existing[0]
