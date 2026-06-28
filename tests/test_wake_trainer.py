from __future__ import annotations

import io
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from unittest.mock import patch


def _make_app():
    from core.main import create_app
    return create_app()


def _fake_samples_dir(tmp_path):
    return tmp_path / "wake_samples"


@pytest.mark.asyncio
async def test_list_phrases_empty(tmp_path):
    with patch("dashboard.server._wake_samples_dir", return_value=tmp_path / "wake_samples"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/wake/phrases")
    assert r.status_code == 200
    assert r.json()["phrases"] == []


@pytest.mark.asyncio
async def test_upload_sample_creates_file(tmp_path):
    with patch("dashboard.server._wake_samples_dir", return_value=tmp_path / "wake_samples"):
        wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20 + b"data\x00\x00\x00\x00"
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post(
                "/api/wake/phrases/hey_plia/samples",
                files={"file": ("sample.wav", io.BytesIO(wav_bytes), "audio/wav")},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["phrase"] == "hey_plia"
    assert data["total_samples"] == 1


@pytest.mark.asyncio
async def test_upload_increments_count(tmp_path):
    with patch("dashboard.server._wake_samples_dir", return_value=tmp_path / "wake_samples"):
        wav_bytes = b"RIFF" + b"\x00" * 40
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            for i in range(3):
                r = await c.post(
                    "/api/wake/phrases/my_phrase/samples",
                    files={"file": (f"s{i}.wav", io.BytesIO(wav_bytes), "audio/wav")},
                )
        assert r.json()["total_samples"] == 3


@pytest.mark.asyncio
async def test_list_phrases_shows_uploaded(tmp_path):
    samples_dir = tmp_path / "wake_samples"
    phrase_dir = samples_dir / "hello_plia"
    phrase_dir.mkdir(parents=True)
    (phrase_dir / "sample_001.wav").write_bytes(b"wav")
    (phrase_dir / "sample_002.wav").write_bytes(b"wav")

    with patch("dashboard.server._wake_samples_dir", return_value=samples_dir):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/wake/phrases")
    phrases = r.json()["phrases"]
    assert len(phrases) == 1
    assert phrases[0]["phrase"] == "hello_plia"
    assert phrases[0]["sample_count"] == 2


@pytest.mark.asyncio
async def test_list_samples_for_phrase(tmp_path):
    samples_dir = tmp_path / "wake_samples"
    phrase_dir = samples_dir / "hey_test"
    phrase_dir.mkdir(parents=True)
    (phrase_dir / "sample_001.wav").write_bytes(b"wav_data")

    with patch("dashboard.server._wake_samples_dir", return_value=samples_dir):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/wake/phrases/hey_test/samples")
    data = r.json()
    assert data["phrase"] == "hey_test"
    assert len(data["samples"]) == 1
    assert data["samples"][0]["name"] == "sample_001.wav"


@pytest.mark.asyncio
async def test_delete_phrase(tmp_path):
    samples_dir = tmp_path / "wake_samples"
    phrase_dir = samples_dir / "bye_phrase"
    phrase_dir.mkdir(parents=True)
    (phrase_dir / "sample_001.wav").write_bytes(b"wav")

    with patch("dashboard.server._wake_samples_dir", return_value=samples_dir):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/wake/phrases/bye_phrase")
    assert r.json()["ok"] is True
    assert not phrase_dir.exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_phrase_404(tmp_path):
    with patch("dashboard.server._wake_samples_dir", return_value=tmp_path / "wake_samples"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/wake/phrases/nonexistent")
    assert r.status_code == 404
