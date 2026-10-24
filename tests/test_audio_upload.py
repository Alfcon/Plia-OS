from __future__ import annotations

import io
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_upload_wav_ok(tmp_path):
    from unittest.mock import patch
    from pathlib import Path

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("test.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
            )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["filename"].endswith(".wav")
    assert d["size"] == 44


@pytest.mark.asyncio
async def test_upload_mp3_ok(tmp_path):
    from unittest.mock import patch

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("track.mp3", b"ID3" + b"\x00" * 10, "audio/mpeg")},
            )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_upload_unsupported_format_415(tmp_path):
    from unittest.mock import patch

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
            )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_upload_sanitises_filename(tmp_path):
    from unittest.mock import patch

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("my file (1).wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
            )
    assert r.status_code == 200
    assert " " not in r.json()["filename"]
    assert "(" not in r.json()["filename"]


@pytest.mark.asyncio
async def test_upload_does_not_conflict_with_clip_get(tmp_path):
    """POST /api/clips/upload must not be captured by GET /api/clips/{filename}."""
    from unittest.mock import patch

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("check.wav", b"RIFF" + b"\x00" * 40, "audio/wav")},
            )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_upload_ogg_ok(tmp_path):
    from unittest.mock import patch

    with patch("dashboard.server.UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/clips/upload",
                files={"file": ("audio.ogg", b"OggS" + b"\x00" * 20, "audio/ogg")},
            )
    assert r.status_code == 200
