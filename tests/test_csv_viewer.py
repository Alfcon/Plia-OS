from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

CSV_SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,London\n"


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_basic_parse():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": CSV_SAMPLE})
    assert r.status_code == 200
    d = r.json()
    assert d["headers"] == ["name", "age", "city"]
    assert d["total"] == 2
    assert d["columns"] == 3


@pytest.mark.asyncio
async def test_rows_content():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": CSV_SAMPLE})
    rows = r.json()["rows"]
    assert rows[0] == ["Alice", "30", "Paris"]
    assert rows[1] == ["Bob", "25", "London"]


@pytest.mark.asyncio
async def test_no_header():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": "a,b,c\n1,2,3\n", "header": False})
    d = r.json()
    assert d["headers"] == ["col0", "col1", "col2"]
    assert d["total"] == 2


@pytest.mark.asyncio
async def test_custom_delimiter():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": "a;b;c\n1;2;3\n", "delimiter": ";"})
    d = r.json()
    assert d["headers"] == ["a", "b", "c"]
    assert d["rows"][0] == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_empty_text():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": ""})
    d = r.json()
    assert d["total"] == 0
    assert d["headers"] == []


@pytest.mark.asyncio
async def test_max_rows_respected():
    rows = "\n".join(f"r{i},val{i}" for i in range(100))
    text = "col1,col2\n" + rows + "\n"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": text, "max_rows": 10})
    assert r.json()["total"] == 10


@pytest.mark.asyncio
async def test_columns_field():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/csv/parse", json={"text": CSV_SAMPLE})
    assert r.json()["columns"] == 3
