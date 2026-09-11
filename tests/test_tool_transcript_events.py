import httpx
import respx
import pytest
from core.registry import tool
from core.supervisor import run_turn
from core import events


@pytest.mark.asyncio
@respx.mock
async def test_tool_call_emits_transcript_event():
    captured = []

    async def capture(payload):
        if payload.get("type") == "transcript" and payload.get("role") == "tool":
            captured.append(payload)

    events.subscribe(capture)
    try:
        @tool(description="returns hello")
        def _greet_tool() -> str:
            return "hello world"

        respx.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "respond", "tool_calls": None}
                }),
                httpx.Response(200, json={
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "t1", "function": {"name": "_greet_tool", "arguments": {}}}],
                    }
                }),
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "I said hello.", "tool_calls": None}
                }),
            ]
        )

        await run_turn([{"role": "user", "content": "say hello"}])

        assert len(captured) == 1
        assert "_greet_tool" in captured[0]["text"]
        assert "hello world" in captured[0]["text"]
    finally:
        events.unsubscribe(capture)


@pytest.mark.asyncio
@respx.mock
async def test_multiple_tool_calls_emit_multiple_transcript_events():
    captured = []

    async def capture(payload):
        if payload.get("type") == "transcript" and payload.get("role") == "tool":
            captured.append(payload)

    events.subscribe(capture)
    try:
        @tool(description="returns one")
        def _tool_one() -> str:
            return "result one"

        @tool(description="returns two")
        def _tool_two() -> str:
            return "result two"

        respx.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "respond", "tool_calls": None}
                }),
                httpx.Response(200, json={
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"id": "t1", "function": {"name": "_tool_one", "arguments": {}}},
                            {"id": "t2", "function": {"name": "_tool_two", "arguments": {}}},
                        ],
                    }
                }),
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "Done.", "tool_calls": None}
                }),
            ]
        )

        await run_turn([{"role": "user", "content": "run both tools"}])

        assert len(captured) == 2
        texts = [c["text"] for c in captured]
        assert any("_tool_one" in t and "result one" in t for t in texts)
        assert any("_tool_two" in t and "result two" in t for t in texts)
    finally:
        events.unsubscribe(capture)


@pytest.mark.asyncio
@respx.mock
async def test_tool_error_still_emits_transcript_event():
    captured = []

    async def capture(payload):
        if payload.get("type") == "transcript" and payload.get("role") == "tool":
            captured.append(payload)

    events.subscribe(capture)
    try:
        @tool(description="always fails")
        def _failing_tool() -> str:
            raise RuntimeError("boom")

        respx.post("http://localhost:11434/api/chat").mock(
            side_effect=[
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "respond", "tool_calls": None}
                }),
                httpx.Response(200, json={
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "t1", "function": {"name": "_failing_tool", "arguments": {}}}],
                    }
                }),
                httpx.Response(200, json={
                    "message": {"role": "assistant", "content": "Sorry.", "tool_calls": None}
                }),
            ]
        )

        await run_turn([{"role": "user", "content": "do the thing"}])

        assert len(captured) == 1
        assert "Error" in captured[0]["text"]
        assert "boom" in captured[0]["text"]
    finally:
        events.unsubscribe(capture)
