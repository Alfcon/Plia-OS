"""Tests for tool_calls support in OpenAI and Anthropic fallback adapters."""
import json
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.llm import _to_anthropic_messages


def _make_config(provider="openai", model="gpt-4o", api_key="key"):
    cfg = MagicMock()
    cfg.fallback_provider = provider
    cfg.fallback_model = model
    cfg.fallback_api_key = api_key
    return cfg


def _mock_openai_module(response):
    """Inject a fake openai module that returns the given response."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mod = types.ModuleType("openai")
    mod.AsyncOpenAI = MagicMock(return_value=mock_client)
    return mod


def _mock_anthropic_module(response):
    """Inject a fake anthropic module that returns the given response."""
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=response)
    mod = types.ModuleType("anthropic")
    mod.AsyncAnthropic = MagicMock(return_value=mock_client)

    # minimal type stubs for isinstance checks
    class TextBlock:
        def __init__(self, text):
            self.text = text

    class ToolUseBlock:
        def __init__(self, id, name, input):
            self.id = id
            self.name = name
            self.input = input

    types_mod = types.ModuleType("anthropic.types")
    types_mod.TextBlock = TextBlock
    types_mod.ToolUseBlock = ToolUseBlock
    mod.types = types_mod
    return mod, TextBlock, ToolUseBlock


# ── OpenAI ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_tool_call_returned():
    from agents.llm import _call_openai

    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = "search_web"
    tc.function.arguments = json.dumps({"query": "plia"})

    choice = MagicMock()
    choice.message.content = None
    choice.message.tool_calls = [tc]

    response = MagicMock()
    response.choices = [choice]

    fake_mod = _mock_openai_module(response)
    with patch.dict(sys.modules, {"openai": fake_mod}):
        result = await _call_openai(
            [{"role": "user", "content": "search for plia"}],
            tools=[{"function": {"name": "search_web", "parameters": {}}}],
            config=_make_config(),
        )

    assert result["role"] == "assistant"
    assert result["tool_calls"][0]["function"]["name"] == "search_web"
    assert result["tool_calls"][0]["function"]["arguments"] == {"query": "plia"}
    assert result["tool_calls"][0]["id"] == "call_1"


@pytest.mark.asyncio
async def test_openai_no_tool_call_unchanged():
    from agents.llm import _call_openai

    choice = MagicMock()
    choice.message.content = "hello"
    choice.message.tool_calls = None

    response = MagicMock()
    response.choices = [choice]

    fake_mod = _mock_openai_module(response)
    with patch.dict(sys.modules, {"openai": fake_mod}):
        result = await _call_openai(
            [{"role": "user", "content": "hi"}],
            tools=None,
            config=_make_config(),
        )

    assert result == {"role": "assistant", "content": "hello"}
    assert "tool_calls" not in result


# ── _to_anthropic_messages ─────────────────────────────────────────────────


def test_to_anthropic_messages_plain():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert _to_anthropic_messages(msgs) == msgs


def test_to_anthropic_messages_tool_role_becomes_tool_result():
    msgs = [
        {"role": "user", "content": "search"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "search_web", "arguments": {"q": "x"}}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "result text"},
    ]
    out = _to_anthropic_messages(msgs)
    assert out[0] == {"role": "user", "content": "search"}
    assert out[1]["role"] == "assistant"
    assert out[1]["content"][0]["type"] == "tool_use"
    assert out[1]["content"][0]["name"] == "search_web"
    assert out[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "result text"}
    ]}


def test_to_anthropic_messages_consecutive_tool_roles_grouped():
    msgs = [
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "tool", "tool_call_id": "c2", "content": "r2"},
    ]
    out = _to_anthropic_messages(msgs)
    assert len(out) == 1
    assert len(out[0]["content"]) == 2


# ── Anthropic ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_tool_use_block_returned_as_tool_calls():
    from agents.llm import _call_anthropic

    fake_mod, TextBlock, ToolUseBlock = _mock_anthropic_module(None)
    tool_block = ToolUseBlock(id="tu_1", name="get_weather", input={"city": "Paris"})

    response = MagicMock()
    response.content = [tool_block]
    fake_mod.AsyncAnthropic.return_value.messages.create = AsyncMock(return_value=response)

    with patch.dict(sys.modules, {"anthropic": fake_mod, "anthropic.types": fake_mod.types}):
        result = await _call_anthropic(
            [{"role": "user", "content": "weather in Paris"}],
            tools=[{"function": {"name": "get_weather", "parameters": {}}}],
            config=_make_config(provider="anthropic"),
        )

    assert result["role"] == "assistant"
    assert result["tool_calls"][0]["function"]["name"] == "get_weather"
    assert result["tool_calls"][0]["function"]["arguments"] == {"city": "Paris"}


@pytest.mark.asyncio
async def test_anthropic_text_only_no_tool_calls_key():
    from agents.llm import _call_anthropic

    fake_mod, TextBlock, ToolUseBlock = _mock_anthropic_module(None)
    text_block = TextBlock(text="sure thing")

    response = MagicMock()
    response.content = [text_block]
    fake_mod.AsyncAnthropic.return_value.messages.create = AsyncMock(return_value=response)

    with patch.dict(sys.modules, {"anthropic": fake_mod, "anthropic.types": fake_mod.types}):
        result = await _call_anthropic(
            [{"role": "user", "content": "hi"}],
            tools=None,
            config=_make_config(provider="anthropic"),
        )

    assert result == {"role": "assistant", "content": "sure thing"}
    assert "tool_calls" not in result
