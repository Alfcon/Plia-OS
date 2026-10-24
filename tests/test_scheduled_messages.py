from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_list_empty():
    with patch("core.scheduled_msg_store.list_scheduled_messages", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/scheduled/messages")
    assert r.status_code == 200
    assert r.json()["messages"] == []


@pytest.mark.asyncio
async def test_add_message_ok():
    with patch("core.scheduled_msg_store.add_scheduled_message", return_value=1):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/scheduled/messages", json={
                "message": "hello pipeline", "fire_at": "2099-01-01T12:00:00Z"
            })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["id"] == 1


@pytest.mark.asyncio
async def test_add_missing_message_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/scheduled/messages", json={"fire_at": "2099-01-01T12:00:00Z"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_add_missing_fire_at_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/scheduled/messages", json={"message": "hi"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_ok():
    with patch("core.scheduled_msg_store.delete_scheduled_message", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/scheduled/messages/1")
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_not_found_404():
    with patch("core.scheduled_msg_store.delete_scheduled_message", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/scheduled/messages/999")
    assert r.status_code == 404


# ── Store unit tests ──────────────────────────────────────────────────────────

def test_store_add_and_list(tmp_path):
    with patch("core.scheduled_msg_store._path", return_value=tmp_path / "sched.json"):
        from core.scheduled_msg_store import add_scheduled_message, list_scheduled_messages
        msg_id = add_scheduled_message("test msg", "2099-01-01T00:00:00Z")
        msgs = list_scheduled_messages()
    assert len(msgs) == 1
    assert msgs[0]["message"] == "test msg"
    assert msgs[0]["id"] == msg_id
    assert not msgs[0]["done"]


def test_store_delete(tmp_path):
    with patch("core.scheduled_msg_store._path", return_value=tmp_path / "sched.json"):
        from core.scheduled_msg_store import add_scheduled_message, delete_scheduled_message, list_scheduled_messages
        msg_id = add_scheduled_message("bye", "2099-01-01T00:00:00Z")
        assert delete_scheduled_message(msg_id) is True
        assert list_scheduled_messages() == []


def test_store_mark_done(tmp_path):
    with patch("core.scheduled_msg_store._path", return_value=tmp_path / "sched.json"):
        from core.scheduled_msg_store import add_scheduled_message, mark_scheduled_done, list_scheduled_messages
        msg_id = add_scheduled_message("done", "2099-01-01T00:00:00Z")
        assert mark_scheduled_done(msg_id) is True
        assert list_scheduled_messages() == []  # done=True filtered out


def test_store_get_pending_past(tmp_path):
    with patch("core.scheduled_msg_store._path", return_value=tmp_path / "sched.json"):
        from core.scheduled_msg_store import add_scheduled_message, get_pending_scheduled
        add_scheduled_message("past", "2000-01-01T00:00:00Z")
        add_scheduled_message("future", "2099-01-01T00:00:00Z")
        pending = get_pending_scheduled()
    assert len(pending) == 1
    assert pending[0]["message"] == "past"
