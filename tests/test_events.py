import asyncio
import pytest
from core import events


async def test_emit_calls_async_subscriber():
    received = []

    async def handler(payload):
        received.append(payload)

    events.subscribe(handler)
    await events.emit("test_event", {"value": 42})
    assert received == [{"type": "test_event", "value": 42}]


async def test_emit_calls_sync_subscriber():
    received = []

    def handler(payload):
        received.append(payload)

    events.subscribe(handler)
    await events.emit("ping", {})
    assert len(received) == 1
    assert received[0]["type"] == "ping"


async def test_unsubscribe_stops_delivery():
    received = []

    async def handler(payload):
        received.append(payload)

    events.subscribe(handler)
    events.unsubscribe(handler)
    await events.emit("after", {})
    assert received == []


async def test_multiple_subscribers_all_called():
    log = []
    events.subscribe(lambda p: log.append("a"))
    events.subscribe(lambda p: log.append("b"))
    await events.emit("x", {})
    assert sorted(log) == ["a", "b"]
