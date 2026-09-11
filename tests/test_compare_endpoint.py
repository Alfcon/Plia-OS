import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from core.main import create_app


class _Resp:
    def __init__(self, data, status=200):
        self._d = data
        self.status_code = status
    def json(self):
        return self._d
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _Client:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, **k):
        if self._exc:
            raise self._exc
        return self._resp


@pytest.mark.asyncio
async def test_run_one_parses_output_and_tokens():
    from dashboard.server import _run_one
    with patch("httpx.AsyncClient",
               return_value=_Client(resp=_Resp({"message": {"content": "hi"}, "eval_count": 7}))):
        r = await _run_one("llama3", "prompt")
    assert r["model"] == "llama3"
    assert r["output"] == "hi"
    assert r["tokens"] == 7
    assert isinstance(r["ms"], int) and r["ms"] >= 0


@pytest.mark.asyncio
async def test_run_one_missing_eval_count_zero_tokens():
    from dashboard.server import _run_one
    with patch("httpx.AsyncClient",
               return_value=_Client(resp=_Resp({"message": {"content": "x"}}))):
        r = await _run_one("m", "p")
    assert r["tokens"] == 0


@pytest.mark.asyncio
async def test_run_one_error_never_raises():
    from dashboard.server import _run_one
    with patch("httpx.AsyncClient", return_value=_Client(exc=RuntimeError("ollama down"))):
        r = await _run_one("m", "p")
    assert r["output"].startswith("Error:")
    assert r["tokens"] == 0
    assert isinstance(r["ms"], int)


async def _fake_run_one(model, prompt):
    return {"model": model, "output": f"out-{model}", "ms": 1, "tokens": 2}


@pytest.mark.asyncio
async def test_compare_endpoint_returns_both():
    transport = ASGITransport(app=create_app())
    with patch("dashboard.server._run_one", new=_fake_run_one):
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post("/api/compare",
                              json={"prompt": "hi", "model_a": "A", "model_b": "B"})
    assert r.status_code == 200
    d = r.json()
    assert d["a"]["model"] == "A" and d["b"]["model"] == "B"
    assert "out-A" in d["a"]["output"] and "out-B" in d["b"]["output"]


@pytest.mark.asyncio
async def test_compare_endpoint_missing_field_400():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/compare", json={"prompt": "hi", "model_a": "A"})
    assert r.status_code == 400
