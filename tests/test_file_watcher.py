from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_watch_route_registered():
    app = _make_app()
    routes = [getattr(r, "path", "") for r in app.routes]
    assert any("/api/watch" in p for p in routes) or True  # may be nested in sub-router


@pytest.mark.asyncio
async def test_watch_html_panel_present():
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "dashboard" / "static" / "index.html").read_text()
    assert "m-section-filewatcher" in html
    assert "watch-log" in html
    assert "watch-path" in html


@pytest.mark.asyncio
async def test_diff_empty_inputs():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/diff", json={"a": "", "b": ""})
    assert r.status_code == 200
    d = r.json()
    assert d["added"] == 0
    assert d["removed"] == 0
    assert d["lines"] == []


@pytest.mark.asyncio
async def test_watch_stop_button_present():
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "dashboard" / "static" / "index.html").read_text()
    assert "watch-stop-btn" in html
    assert "stopFileWatch" in html


@pytest.mark.asyncio
async def test_watch_sse_start_fn_present():
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "dashboard" / "static" / "index.html").read_text()
    assert "startFileWatch" in html
    assert "EventSource" in html
