from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_voice_level_returns_zero_when_pipeline_not_running():
    import voice.pipeline as vp
    vp._CURRENT_AUDIO_LEVEL = 0.0
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/voice/level")
    assert r.status_code == 200
    data = r.json()
    assert "level" in data
    assert data["level"] == 0.0


@pytest.mark.asyncio
async def test_voice_level_reflects_module_value():
    import voice.pipeline as vp
    vp._CURRENT_AUDIO_LEVEL = 0.1234
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/voice/level")
    data = r.json()
    assert abs(data["level"] - 0.1234) < 0.0001
    vp._CURRENT_AUDIO_LEVEL = 0.0


@pytest.mark.asyncio
async def test_voice_level_rounded_to_4dp():
    import voice.pipeline as vp
    vp._CURRENT_AUDIO_LEVEL = 0.123456789
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/voice/level")
    data = r.json()
    assert data["level"] == round(0.123456789, 4)
    vp._CURRENT_AUDIO_LEVEL = 0.0


@pytest.mark.asyncio
async def test_voice_level_handles_import_error(monkeypatch):
    import sys
    orig = sys.modules.get("voice.pipeline")
    sys.modules["voice.pipeline"] = None  # type: ignore[assignment]
    try:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/voice/level")
        assert r.status_code == 200
        assert r.json()["level"] == 0.0
    finally:
        if orig is not None:
            sys.modules["voice.pipeline"] = orig
        else:
            del sys.modules["voice.pipeline"]


@pytest.mark.asyncio
async def test_voice_level_zero_after_silence():
    import voice.pipeline as vp
    vp._CURRENT_AUDIO_LEVEL = 0.0
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/voice/level")
    assert r.json()["level"] == 0.0
