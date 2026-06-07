# tests/test_vram_broker.py
import pytest
from unittest.mock import MagicMock
from voice.vram_broker import VRAMBroker, ModelEntry, get_vram_broker
import voice.vram_broker as broker_module

LIGHT = 1
HEAVY = 3


@pytest.fixture(autouse=True)
def reset_broker():
    broker_module._broker = None
    yield
    broker_module._broker = None


def _make_entry(name, priority, vram_gb=1.0):
    return ModelEntry(
        name=name,
        priority=priority,
        vram_gb=vram_gb,
        load_fn=MagicMock(),
        unload_fn=MagicMock(),
    )


def test_request_loads_model():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1)
    b.register(e)
    b.request("kokoro")
    e.load_fn.assert_called_once()
    assert e.state == "gpu"


def test_request_noop_if_already_on_gpu():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1)
    b.register(e)
    b.request("kokoro")
    b.request("kokoro")
    e.load_fn.assert_called_once()  # not twice


def test_request_evicts_lower_priority():
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    heavy = _make_entry("dramabox", 3, vram_gb=8.5)
    b.register(light)
    b.register(heavy)
    b.request("kokoro")
    b.request("dramabox")
    light.unload_fn.assert_called_once()
    assert light.state == "unloaded"
    assert heavy.state == "gpu"


def test_request_does_not_evict_equal_priority():
    b = VRAMBroker()
    e1 = _make_entry("kokoro", 1)
    e2 = _make_entry("whisper", 1)
    b.register(e1)
    b.register(e2)
    b.request("kokoro")
    b.request("whisper")
    e1.unload_fn.assert_not_called()
    assert e2.state == "gpu"


def test_second_heavy_releases_first():
    b = VRAMBroker()
    h1 = _make_entry("chatterbox", 3)
    h2 = _make_entry("dramabox", 3)
    b.register(h1)
    b.register(h2)
    b.request("chatterbox")
    b.request("dramabox")
    h1.unload_fn.assert_called_once()
    assert h1.state == "unloaded"
    assert h2.state == "gpu"


def test_release_unloads_and_restores_evicted():
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    heavy = _make_entry("dramabox", 3)
    b.register(light)
    b.register(heavy)
    b.request("kokoro")
    b.request("dramabox")   # evicts kokoro
    b.release("dramabox")
    assert light.load_fn.call_count == 2  # once for initial load, once for restore
    assert light.state == "gpu"
    assert heavy.state == "unloaded"


def test_release_noop_if_unloaded():
    b = VRAMBroker()
    e = _make_entry("dramabox", 3)
    b.register(e)
    b.release("dramabox")   # never loaded — should not raise
    e.unload_fn.assert_not_called()


def test_status_reflects_state():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1, vram_gb=0.4)
    b.register(e)
    b.request("kokoro")
    s = b.status()
    assert s["models"]["kokoro"]["state"] == "gpu"
    assert "vram_total_gb" in s
    assert "studio_mode" in s


def test_status_studio_mode_true_when_heavy_loaded():
    b = VRAMBroker()
    e = _make_entry("chatterbox", 3)
    b.register(e)
    b.request("chatterbox")
    s = b.status()
    assert s["studio_mode"] is True
    assert s["active_heavy"] == "chatterbox"


def test_get_vram_broker_returns_singleton():
    b1 = get_vram_broker()
    b2 = get_vram_broker()
    assert b1 is b2


def test_heavy_to_heavy_swap_does_not_restore_lights_from_first_session():
    """When swapping between two heavy models, lights evicted for the first
    heavy are abandoned — only lights evicted for the second heavy are restored."""
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    h1 = _make_entry("chatterbox", 3)
    h2 = _make_entry("dramabox", 3)
    b.register(light)
    b.register(h1)
    b.register(h2)
    b.request("kokoro")         # kokoro on GPU
    b.request("chatterbox")     # evicts kokoro (_evicted=["kokoro"]), loads chatterbox
    b.request("dramabox")       # releases chatterbox, resets _evicted=[], loads dramabox
    # Now release dramabox — _evicted is [] so nothing is restored
    b.release("dramabox")
    assert light.state == "unloaded"   # kokoro is gone — this is expected
    assert light.load_fn.call_count == 1  # called once (initial), never restored


# --- Endpoint tests (Task 4) ---
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from unittest.mock import patch as _patch, MagicMock as _MagicMock
from dashboard.server import router as _router
from core.config import reset_config as _reset_config, update_config as _update_config, get_config as _get_config


@pytest.fixture
def _app():
    a = FastAPI()
    a.include_router(_router)
    return a


@pytest.fixture(autouse=False)
def _reset_cfg():
    yield
    _reset_config()


async def test_vram_status_returns_dict(_app, _reset_cfg):
    mock_broker = _MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.5, "vram_total_gb": 7.6,
    }
    with _patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            resp = await client.get("/api/vram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "studio_mode" in data
    assert "vram_total_gb" in data


async def test_vram_release_calls_broker(_app, _reset_cfg):
    mock_broker = _MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.0, "vram_total_gb": 7.6,
    }
    with _patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            resp = await client.post("/api/vram/release", json={"name": "dramabox"})
    assert resp.status_code == 200
    mock_broker.release.assert_called_once_with("dramabox")


async def test_vram_release_missing_name_returns_422(_app):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        resp = await client.post("/api/vram/release", json={})
    assert resp.status_code == 422


async def test_vram_release_reverts_tts_engine_to_kokoro(_app, _reset_cfg):
    _update_config(tts_engine="dramabox")
    mock_broker = _MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.0, "vram_total_gb": 7.6,
    }
    with _patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            await client.post("/api/vram/release", json={"name": "dramabox"})
    assert _get_config().tts_engine == "kokoro"
