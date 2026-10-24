from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _silence(seconds: float = 1.0, sr: int = 16000) -> bytes:
    return np.zeros(int(seconds * sr), dtype=np.float32).tobytes()


def _mock_wake_model(scores: dict | None = None):
    m = MagicMock()
    m.predict.return_value = scores or {"hey_jarvis_v0.1": 0.1, "alexa_v0.1": 0.05}
    return m


# ── GET /api/wake/models ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_models_returns_list():
    with patch("dashboard.server._get_wake_model"):
        with patch("openwakeword.get_pretrained_model_paths", return_value=["/models/alexa_v0.1.onnx", "/models/hey_jarvis_v0.1.onnx"]):
            async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                r = await c.get("/api/wake/models")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert "threshold" in data
    assert isinstance(data["models"], list)


@pytest.mark.asyncio
async def test_wake_models_includes_threshold():
    with patch("openwakeword.get_pretrained_model_paths", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/wake/models")
    assert r.json()["threshold"] > 0


# ── POST /api/wake/test ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_test_returns_scores():
    with patch("dashboard.server._run_wake_prediction", return_value={"alexa_v0.1": 0.02, "hey_jarvis_v0.1": 0.91}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/wake/test",
                content=_silence(), headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    data = r.json()
    assert "scores" in data
    assert "alexa_v0.1" in data["scores"]


@pytest.mark.asyncio
async def test_wake_test_detects_above_threshold():
    with patch("dashboard.server._run_wake_prediction", return_value={"hey_jarvis_v0.1": 0.95}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/wake/test",
                content=_silence(), headers={"Content-Type": "application/octet-stream"})
    data = r.json()
    assert "hey_jarvis_v0.1" in data["detected_by"]


@pytest.mark.asyncio
async def test_wake_test_no_detection_below_threshold():
    with patch("dashboard.server._run_wake_prediction", return_value={"hey_jarvis_v0.1": 0.01}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/wake/test",
                content=_silence(), headers={"Content-Type": "application/octet-stream"})
    assert r.json()["detected_by"] == []


@pytest.mark.asyncio
async def test_wake_test_empty_body_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/wake/test",
            content=b"", headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_wake_test_engine_error_500():
    with patch("dashboard.server._run_wake_prediction", side_effect=RuntimeError("model failed")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/wake/test",
                content=_silence(), headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 500
    assert "model failed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_wake_test_scores_rounded():
    with patch("dashboard.server._run_wake_prediction", return_value={"alexa_v0.1": 0.123456789}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/wake/test",
                content=_silence(), headers={"Content-Type": "application/octet-stream"})
    score = r.json()["scores"]["alexa_v0.1"]
    assert len(str(score).split(".")[-1]) <= 4


# ── _run_wake_prediction (unit) ───────────────────────────────────────────────

def test_run_prediction_calls_predict_in_chunks():
    import dashboard.server as srv
    call_count = 0
    scores = {}

    def fake_predict(chunk):
        nonlocal call_count
        call_count += 1
        return {"alexa_v0.1": 0.1}

    mock_model = MagicMock()
    mock_model.predict.side_effect = fake_predict

    with patch("dashboard.server._get_wake_model", return_value=mock_model):
        audio = np.zeros(16000, dtype=np.int16)
        scores = srv._run_wake_prediction(audio)

    assert mock_model.predict.call_count > 1
    assert "alexa_v0.1" in scores


def test_run_prediction_skips_numeric_keys():
    import dashboard.server as srv

    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis_v0.1": 0.5, "0": 0.9, "1": 0.8}

    with patch("dashboard.server._get_wake_model", return_value=mock_model):
        audio = np.zeros(1280, dtype=np.int16)
        scores = srv._run_wake_prediction(audio)

    assert "0" not in scores
    assert "1" not in scores
    assert "hey_jarvis_v0.1" in scores


def test_run_prediction_tracks_max_score():
    import dashboard.server as srv
    call_n = 0

    def varying_predict(chunk):
        nonlocal call_n
        call_n += 1
        return {"alexa_v0.1": 0.9 if call_n == 3 else 0.1}

    mock_model = MagicMock()
    mock_model.predict.side_effect = varying_predict

    with patch("dashboard.server._get_wake_model", return_value=mock_model):
        audio = np.zeros(1280 * 5, dtype=np.int16)
        scores = srv._run_wake_prediction(audio)

    assert scores["alexa_v0.1"] == pytest.approx(0.9, abs=0.01)
