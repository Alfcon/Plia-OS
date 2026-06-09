import pytest
from unittest.mock import AsyncMock, patch
from core.config import reset_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def _state(user_text, search_provider="ddg"):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": search_provider,
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_web_node_returns_tool_results():
    from agents.web import web_node

    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "python language"}
        mock_ws.return_value = ["Python: A language (https://python.org)"]
        update = await web_node(_state("search for python language"))
    assert update["active_agent"] == "web"
    assert any("Python" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_web_node_detects_google_keyword():
    from agents.web import web_node

    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "best python tutorials"}
        mock_ws.return_value = ["result"]
        await web_node(_state("search with google for best python tutorials"))
    args, _ = mock_ws.call_args
    assert args[1] == "google"


@pytest.mark.asyncio
async def test_web_node_detects_url_for_playwright():
    from agents.web import web_node

    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "https://example.com"}
        mock_ws.return_value = ["page content"]
        await web_node(_state("open https://example.com and summarise it"))
    args, _ = mock_ws.call_args
    assert args[1] == "playwright"


@pytest.mark.asyncio
async def test_web_node_uses_state_provider_as_default():
    from agents.web import web_node

    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "latest news"}
        mock_ws.return_value = ["news result"]
        await web_node(_state("what is the latest news", search_provider="ddg"))
    args, _ = mock_ws.call_args
    assert args[1] == "ddg"


@pytest.mark.asyncio
async def test_web_node_llm_error_uses_raw_message_as_query():
    from agents.web import web_node

    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.side_effect = RuntimeError("llm down")
        mock_ws.return_value = ["result"]
        update = await web_node(_state("find something interesting"))
    args, _ = mock_ws.call_args
    assert "find something interesting" in args[0]
    assert update["active_agent"] == "web"
