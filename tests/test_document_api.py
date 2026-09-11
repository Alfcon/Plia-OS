from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_store(sources=None, query_result="result text", index_result="Indexed 1 file(s) → 3 chunk(s)."):
    store = MagicMock()
    store.list_sources.return_value = sources or []
    store.query.return_value = query_result
    store.index_directory.return_value = index_result
    store.delete_source.return_value = 3
    return store


@pytest.mark.asyncio
async def test_list_sources_empty():
    with patch("agents.document_store.get_document_store", return_value=_mock_store()):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/documents/sources")
    assert r.status_code == 200
    assert r.json()["sources"] == []


@pytest.mark.asyncio
async def test_list_sources_populated():
    store = _mock_store(sources=["/home/user/a.txt", "/home/user/b.md"])
    with patch("agents.document_store.get_document_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/documents/sources")
    assert r.status_code == 200
    assert len(r.json()["sources"]) == 2


@pytest.mark.asyncio
async def test_index_documents():
    store = _mock_store()
    with patch("agents.document_store.get_document_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/documents/index", json={"directory": "/tmp/docs", "glob": "**/*.md"})
    assert r.status_code == 200
    assert "Indexed" in r.json()["result"]
    store.index_directory.assert_called_once_with("/tmp/docs", "**/*.md")


@pytest.mark.asyncio
async def test_index_documents_missing_directory():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/documents/index", json={"glob": "**/*.txt"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_remove_source():
    store = _mock_store()
    with patch("agents.document_store.get_document_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/documents/remove", json={"source": "/home/user/a.txt"})
    assert r.status_code == 200
    assert r.json()["removed"] == 3
    store.delete_source.assert_called_once_with("/home/user/a.txt")


@pytest.mark.asyncio
async def test_remove_source_missing_body():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/documents/remove", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_documents():
    store = _mock_store(query_result="[notes.txt] Some relevant text here")
    with patch("agents.document_store.get_document_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/documents/search", json={"query": "relevant topic", "n_results": 3})
    assert r.status_code == 200
    assert "relevant" in r.json()["result"]
    store.query.assert_called_once_with("relevant topic", 3)


@pytest.mark.asyncio
async def test_search_documents_missing_query():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/documents/search", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_n_results_clamped():
    store = _mock_store()
    with patch("agents.document_store.get_document_store", return_value=store):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/documents/search", json={"query": "test", "n_results": 999})
    store.query.assert_called_once_with("test", 20)
