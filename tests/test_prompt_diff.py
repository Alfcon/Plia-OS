from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_diff_returns_200():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/system-prompt/diff")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_diff_has_vs_default_key():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/system-prompt/diff")
    data = r.json()
    assert "vs_default" in data
    assert isinstance(data["vs_default"], list)


@pytest.mark.asyncio
async def test_diff_has_backup_key():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/system-prompt/diff")
    data = r.json()
    assert "vs_backup" in data
    assert "has_backup" in data


@pytest.mark.asyncio
async def test_diff_no_diff_when_unchanged():
    # Fresh config: system_prompt matches default, so vs_default should be empty
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/system-prompt/diff")
    assert r.json()["vs_default"] == []


@pytest.mark.asyncio
async def test_diff_detects_change():
    from core.config import get_config, update_config
    original = get_config().system_prompt
    try:
        update_config(system_prompt="Modified prompt for testing.")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/system-prompt/diff")
        lines = r.json()["vs_default"]
        assert len(lines) > 0
        kinds = {l["kind"] for l in lines}
        assert "add" in kinds or "remove" in kinds
    finally:
        update_config(system_prompt=original)


@pytest.mark.asyncio
async def test_diff_line_kinds():
    from core.config import get_config, update_config
    original = get_config().system_prompt
    try:
        update_config(system_prompt="Brand new prompt.")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/system-prompt/diff")
        for line in r.json()["vs_default"]:
            assert line["kind"] in ("add", "remove", "meta", "context")
            assert "line" in line
    finally:
        update_config(system_prompt=original)


@pytest.mark.asyncio
async def test_diff_has_backup_false_when_no_backup():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/system-prompt/diff")
    assert r.json()["has_backup"] is False
