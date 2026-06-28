from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _patch_uploads(tmp_path):
    return patch("dashboard.server.UPLOADS_DIR", tmp_path)


def _write_clip(tmp_path, name="test.wav", content=b"RIFF\x00\x00\x00\x00WAVEfmt "):
    p = tmp_path / name
    p.write_bytes(content)
    return p


@pytest.mark.asyncio
async def test_list_clips_empty(tmp_path):
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clips")
    assert r.status_code == 200
    assert r.json()["clips"] == []


@pytest.mark.asyncio
async def test_list_clips_returns_audio_files(tmp_path):
    _write_clip(tmp_path, "voice.wav")
    _write_clip(tmp_path, "sample.mp3")
    (tmp_path / "readme.txt").write_text("not audio")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clips")
    data = r.json()
    names = {c["filename"] for c in data["clips"]}
    assert "voice.wav" in names
    assert "sample.mp3" in names
    assert "readme.txt" not in names


@pytest.mark.asyncio
async def test_list_clips_has_metadata(tmp_path):
    _write_clip(tmp_path, "clip.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clips")
    clip = r.json()["clips"][0]
    assert "size" in clip
    assert "modified" in clip
    assert "active_chatterbox" in clip
    assert "active_dramabox" in clip


@pytest.mark.asyncio
async def test_serve_clip(tmp_path):
    _write_clip(tmp_path, "play.wav", b"audio_data")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clips/play.wav")
    assert r.status_code == 200
    assert r.content == b"audio_data"


@pytest.mark.asyncio
async def test_serve_clip_not_found(tmp_path):
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/clips/ghost.wav")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_activate_chatterbox(tmp_path):
    _write_clip(tmp_path, "ref.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/ref.wav/activate", json={"target": "chatterbox"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["target"] == "chatterbox"
    from core.config import get_config
    assert get_config().chatterbox_reference_audio == str(tmp_path / "ref.wav")


@pytest.mark.asyncio
async def test_activate_dramabox(tmp_path):
    _write_clip(tmp_path, "ref.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/ref.wav/activate", json={"target": "dramabox"})
    assert r.status_code == 200
    from core.config import get_config
    assert get_config().dramabox_voice_ref == str(tmp_path / "ref.wav")


@pytest.mark.asyncio
async def test_activate_not_found(tmp_path):
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/ghost.wav/activate", json={"target": "chatterbox"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_clip(tmp_path):
    p = _write_clip(tmp_path, "del.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/clips/del.wav")
    assert r.status_code == 200
    assert not p.exists()


@pytest.mark.asyncio
async def test_delete_clears_active_config(tmp_path):
    _write_clip(tmp_path, "active.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/clips/active.wav/activate", json={"target": "chatterbox"})
            await c.delete("/api/clips/active.wav")
    from core.config import get_config
    assert get_config().chatterbox_reference_audio is None


@pytest.mark.asyncio
async def test_delete_not_found(tmp_path):
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/clips/ghost.wav")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rename_clip(tmp_path):
    _write_clip(tmp_path, "old.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/old.wav/rename", json={"name": "new.wav"})
    assert r.status_code == 200
    assert r.json()["filename"] == "new.wav"
    assert (tmp_path / "new.wav").exists()
    assert not (tmp_path / "old.wav").exists()


@pytest.mark.asyncio
async def test_rename_updates_config(tmp_path):
    _write_clip(tmp_path, "ref.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/clips/ref.wav/activate", json={"target": "chatterbox"})
            await c.post("/api/clips/ref.wav/rename", json={"name": "renamed.wav"})
    from core.config import get_config
    assert get_config().chatterbox_reference_audio == str(tmp_path / "renamed.wav")


@pytest.mark.asyncio
async def test_rename_missing_name(tmp_path):
    _write_clip(tmp_path, "clip.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/clip.wav/rename", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rename_conflict(tmp_path):
    _write_clip(tmp_path, "a.wav")
    _write_clip(tmp_path, "b.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/clips/a.wav/rename", json={"name": "b.wav"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_active_badge_in_list(tmp_path):
    _write_clip(tmp_path, "ref.wav")
    with _patch_uploads(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/clips/ref.wav/activate", json={"target": "chatterbox"})
            r = await c.get("/api/clips")
    clip = next(c for c in r.json()["clips"] if c["filename"] == "ref.wav")
    assert clip["active_chatterbox"] is True
    assert clip["active_dramabox"] is False
