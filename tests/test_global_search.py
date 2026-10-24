from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── chat_history.search ───────────────────────────────────────────────────────

def test_chat_search_returns_matches(tmp_path):
    from agents import chat_history
    with patch.object(chat_history, "_DB_PATH", tmp_path / "ch.db"):
        chat_history._init_db()
        chat_history.add_message("user", "hello world today")
        chat_history.add_message("assistant", "good morning")
        chat_history.add_message("user", "world cup results")
        results = chat_history.search("world")
    assert len(results) == 2
    assert all("world" in r["content"].lower() for r in results)


def test_chat_search_empty_query(tmp_path):
    from agents import chat_history
    with patch.object(chat_history, "_DB_PATH", tmp_path / "ch.db"):
        chat_history._init_db()
        chat_history.add_message("user", "hello")
        results = chat_history.search("")
    assert results == []


def test_chat_search_no_match(tmp_path):
    from agents import chat_history
    with patch.object(chat_history, "_DB_PATH", tmp_path / "ch.db"):
        chat_history._init_db()
        chat_history.add_message("user", "hello")
        results = chat_history.search("xyz123")
    assert results == []


# ── memory_store search methods ───────────────────────────────────────────────

def test_search_facts(tmp_path):
    from unittest.mock import patch as _patch
    with _patch("agents.memory_store.get_memory_store") as mock_get:
        store = MagicMock()
        store.search_facts.return_value = [{"key": "dog_name", "value": "Rex"}]
        mock_get.return_value = store
        result = store.search_facts("dog")
    assert len(result) == 1
    assert result[0]["key"] == "dog_name"


def test_search_reminders(tmp_path):
    from unittest.mock import patch as _patch
    with _patch("agents.memory_store.get_memory_store") as mock_get:
        store = MagicMock()
        store.search_reminders.return_value = [
            {"id": 1, "message": "take medicine", "fire_at": "2026-07-01T09:00:00+00:00", "done": False, "is_timer": False}
        ]
        mock_get.return_value = store
        result = store.search_reminders("medicine")
    assert len(result) == 1
    assert "medicine" in result[0]["message"]


# ── GET /api/search ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_empty_query():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/search?q=")
    assert r.status_code == 200
    assert r.json()["results"] == {}


@pytest.mark.asyncio
async def test_search_returns_structure():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/search?q=test")
    assert r.status_code == 200
    data = r.json()
    assert "query" in data
    assert "results" in data
    assert "total" in data
    assert data["query"] == "test"


@pytest.mark.asyncio
async def test_search_chat_hits():
    with patch("dashboard.server.chat_search", return_value=[
        {"role": "user", "content": "hello world", "ts": "2026-06-28T10:00:00"},
        {"role": "assistant", "content": "world is big", "ts": "2026-06-28T10:00:01"},
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/search?q=world")
    assert r.status_code == 200
    data = r.json()
    assert "chat" in data["results"]
    assert len(data["results"]["chat"]) == 2


@pytest.mark.asyncio
async def test_search_facts_hits():
    store = MagicMock()
    store.search_facts.return_value = [{"key": "dog", "value": "Rex"}]
    store.search_reminders.return_value = []
    with patch("dashboard.server.get_memory_store", return_value=store), \
         patch("dashboard.server.chat_search", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/search?q=dog")
    data = r.json()
    assert "facts" in data["results"]
    assert data["results"]["facts"][0]["key"] == "dog"


@pytest.mark.asyncio
async def test_search_total_count():
    store = MagicMock()
    store.search_facts.return_value = [{"key": "k", "value": "v"}]
    store.search_reminders.return_value = [{"id": 1, "message": "test", "fire_at": "", "done": False, "is_timer": False}]
    with patch("dashboard.server.get_memory_store", return_value=store), \
         patch("dashboard.server.chat_search", return_value=[]), \
         patch("agents.variable_store.list_vars", return_value=[]), \
         patch("agents.workflow_store.list_workflows", return_value=[]), \
         patch("agents.webhook_store.list_webhooks", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/search?q=test")
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_search_workflow_hits():
    wf = [{"name": "morning_flow", "description": "morning routine", "steps": [{"tool": "get_time", "note": ""}]}]
    with patch("dashboard.server.chat_search", return_value=[]), \
         patch("dashboard.server.get_memory_store", return_value=MagicMock(
             search_facts=lambda q, n: [], search_reminders=lambda q, n: [])), \
         patch("agents.variable_store.list_vars", return_value=[]), \
         patch("agents.workflow_store.list_workflows", return_value=wf), \
         patch("agents.webhook_store.list_webhooks", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/search?q=morning")
    data = r.json()
    assert "workflows" in data["results"]
    assert data["results"]["workflows"][0]["name"] == "morning_flow"


@pytest.mark.asyncio
async def test_search_no_results():
    store = MagicMock()
    store.search_facts.return_value = []
    store.search_reminders.return_value = []
    with patch("dashboard.server.get_memory_store", return_value=store), \
         patch("dashboard.server.chat_search", return_value=[]), \
         patch("agents.variable_store.list_vars", return_value=[]), \
         patch("agents.workflow_store.list_workflows", return_value=[]), \
         patch("agents.webhook_store.list_webhooks", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/search?q=zzznomatch")
    assert r.json()["total"] == 0
    assert r.json()["results"] == {}
