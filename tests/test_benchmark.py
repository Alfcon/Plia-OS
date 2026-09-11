from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _ollama_response(content="Paris.", prompt_tokens=10, completion_tokens=5, eval_duration_ns=500_000_000):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
        "eval_duration": eval_duration_ns,
        "total_duration": eval_duration_ns + 100_000_000,
    }
    return mock


# ── POST /api/benchmark ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_returns_structure():
    mock_resp = _ollama_response()
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={"prompt": "What is 1+1?"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "runs" in data
    assert "avg_latency_ms" in data
    assert "avg_tokens_per_sec" in data


@pytest.mark.asyncio
async def test_benchmark_single_run_fields():
    mock_resp = _ollama_response("Paris.", prompt_tokens=8, completion_tokens=4, eval_duration_ns=400_000_000)
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={"prompt": "Capital of France?"})
    data = r.json()
    run = data["runs"][0]
    assert run["prompt_tokens"] == 8
    assert run["completion_tokens"] == 4
    assert run["tokens_per_sec"] == pytest.approx(10.0, abs=0.5)  # 4 tokens / 0.4s
    assert "response_snippet" in run
    assert "latency_ms" in run
    assert "model" in run


@pytest.mark.asyncio
async def test_benchmark_multiple_runs():
    mock_resp = _ollama_response()
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={"prompt": "Hello", "runs": 3})
    data = r.json()
    assert len(data["runs"]) == 3


@pytest.mark.asyncio
async def test_benchmark_runs_capped_at_5():
    mock_resp = _ollama_response()
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={"prompt": "Hi", "runs": 99})
    assert len(r.json()["runs"]) == 5


@pytest.mark.asyncio
async def test_benchmark_uses_default_prompt():
    mock_resp = _ollama_response()
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={})
    data = r.json()
    assert data["ok"] is True
    assert data["runs"][0]["prompt"] != ""


@pytest.mark.asyncio
async def test_benchmark_error_on_ollama_failure():
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(side_effect=Exception("Connection refused"))
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/benchmark", json={"prompt": "Test"})
    data = r.json()
    assert data["ok"] is False
    assert "error" in data


# ── GET /api/benchmark/history ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benchmark_history_empty_initially():
    import dashboard.server as srv
    srv._BENCH_HISTORY.clear()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/benchmark/history")
    assert r.status_code == 200
    assert r.json()["history"] == []


@pytest.mark.asyncio
async def test_benchmark_history_populated_after_run():
    import dashboard.server as srv
    srv._BENCH_HISTORY.clear()
    mock_resp = _ollama_response("Paris.")
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/benchmark", json={"prompt": "Capital?", "runs": 2})
            r = await c.get("/api/benchmark/history")
    data = r.json()
    assert len(data["history"]) == 2
    assert data["history"][0]["response_snippet"] == "Paris."


@pytest.mark.asyncio
async def test_benchmark_history_n_param():
    import dashboard.server as srv
    srv._BENCH_HISTORY.clear()
    mock_resp = _ollama_response()
    with patch("httpx.AsyncClient") as MockClient:
        inst = AsyncMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = inst
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/benchmark", json={"prompt": "Hi", "runs": 5})
            r = await c.get("/api/benchmark/history?n=2")
    assert len(r.json()["history"]) == 2
