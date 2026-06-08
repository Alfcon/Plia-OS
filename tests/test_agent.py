import pytest
import respx
import httpx
from core.supervisor import run_turn
from core.registry import tool


@respx.mock
async def test_plain_text_response():
    respx.post("http://localhost:11434/api/chat").mock(
        side_effect=[
            # Supervisor node: route intent
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "respond", "tool_calls": None}
            }),
            # Respond node: generate response
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "Hello!", "tool_calls": None}
            }),
        ]
    )
    messages = [{"role": "user", "content": "hi"}]
    text, history = await run_turn(messages)
    assert text == "Hello!"
    assert history[-1]["content"] == "Hello!"


@respx.mock
async def test_tool_call_then_text():
    @tool(description="return 42")
    def get_answer() -> int:
        return 42

    # Supervisor node: route intent + respond node: tool call + respond node: final response
    respx.post("http://localhost:11434/api/chat").mock(
        side_effect=[
            # Supervisor node: route to respond
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "respond", "tool_calls": None}
            }),
            # Respond node: tool call
            httpx.Response(200, json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_abc", "function": {"name": "get_answer", "arguments": {}}}],
                }
            }),
            # Respond node: plain text after seeing tool result
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "The answer is 42.", "tool_calls": None}
            }),
        ]
    )

    messages = [{"role": "user", "content": "what is the answer?"}]
    text, history = await run_turn(messages)
    assert text == "The answer is 42."
    # tool result message was appended
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert tool_msgs[0]["content"] == "42"
    assert tool_msgs[0].get("tool_call_id") == "call_abc"


@respx.mock
async def test_tool_error_returned_as_string():
    @tool(description="always explodes")
    def boom() -> str:
        raise RuntimeError("kaboom")

    respx.post("http://localhost:11434/api/chat").mock(
        side_effect=[
            # Supervisor node: route to respond
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "respond", "tool_calls": None}
            }),
            # Respond node: tool call
            httpx.Response(200, json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "boom", "arguments": {}}}],
                }
            }),
            # Respond node: response after error
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "Something went wrong.", "tool_calls": None}
            }),
        ]
    )

    messages = [{"role": "user", "content": "trigger it"}]
    text, history = await run_turn(messages)
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert "kaboom" in tool_msgs[0]["content"]


@respx.mock
async def test_async_tool_is_awaited():
    @tool(description="async answer")
    async def async_answer() -> int:
        return 99

    respx.post("http://localhost:11434/api/chat").mock(
        side_effect=[
            # Supervisor node: route to respond
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "respond", "tool_calls": None}
            }),
            # Respond node: async tool call
            httpx.Response(200, json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_x", "function": {"name": "async_answer", "arguments": {}}}],
                }
            }),
            # Respond node: response after async tool
            httpx.Response(200, json={
                "message": {"role": "assistant", "content": "The async answer is 99.", "tool_calls": None}
            }),
        ]
    )

    messages = [{"role": "user", "content": "async?"}]
    text, history = await run_turn(messages)
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert tool_msgs[0]["content"] == "99"
    assert text == "The async answer is 99."
