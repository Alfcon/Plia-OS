"""Ollama context window must be set explicitly.

Ollama defaults num_ctx to ~4096 when neither the request nor the Modelfile
sets it. Plia registers ~150 tools whose schemas alone are ~13,900 tokens, so
every tool-bearing prompt was silently truncated: the model saw roughly the
first third of the toolset and answered "none of the provided functions..."
for tools that existed the whole time, or free-associated about JSON because
it received schema text severed mid-structure.

Measured against a live qwen2.5:7b with the real 150-tool payload:
  default num_ctx -> prompt_eval_count 4095, no tool call
  num_ctx=32768   -> prompt_eval_count 9242, correctly called clear_conversation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.llm import call_llm


def _mock_post(captured: dict):
    """Capture the JSON body Plia POSTs to Ollama."""
    async def _post(url, json=None, **kw):
        captured.update(json or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"message": {"content": "ok"}})
        return resp
    return _post


@pytest.fixture
def captured(monkeypatch):
    body: dict = {}
    client = MagicMock()
    client.post = _mock_post(body)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("agents.llm.httpx.AsyncClient", MagicMock(return_value=client))
    return body


async def test_num_ctx_is_sent_to_ollama(captured):
    await call_llm([{"role": "user", "content": "hi"}])
    assert "options" in captured, "no options block — Ollama falls back to its ~4096 default"
    assert captured["options"]["num_ctx"] == 16384


async def test_num_ctx_follows_config(captured):
    from core.config import update_config
    update_config(ollama_num_ctx=32768)
    await call_llm([{"role": "user", "content": "hi"}])
    assert captured["options"]["num_ctx"] == 32768


async def test_num_ctx_sent_even_with_tools(captured):
    # The tool-bearing path is the one that actually overflowed.
    await call_llm(
        [{"role": "user", "content": "clear all chat"}],
        tools=[{"type": "function", "function": {"name": "clear_conversation"}}],
    )
    assert captured["options"]["num_ctx"] == 16384
    assert captured["tools"]


def test_default_fits_the_measured_tool_payload():
    # ~13.9k tokens of schemas + system prompt + history must fit, or the
    # truncation bug simply returns at a larger size.
    from core.config import get_config
    assert get_config().ollama_num_ctx >= 16384
