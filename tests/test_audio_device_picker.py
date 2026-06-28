from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_devices():
    return [
        {"name": "pipewire", "max_input_channels": 64, "max_output_channels": 64},
        {"name": "pulse", "max_input_channels": 32, "max_output_channels": 32},
        {"name": "HDA Intel PCH", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "USB Mic", "max_input_channels": 2, "max_output_channels": 0},
    ]


def _mock_sd(devs=None, default=(18, 19)):
    sd = MagicMock()
    sd.query_devices.return_value = devs if devs is not None else _mock_devices()
    sd.default.device = default
    return sd


# ── GET /api/audio/devices ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_devices_returns_list():
    with patch("dashboard.server.asyncio.to_thread", side_effect=lambda f, *a: f(*a)):
        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: _mock_sd() if name == "sounddevice" else __import__(name, *a, **kw)):
            pass  # can't easily mock builtins.__import__ cleanly
    # Use direct sounddevice patch
    sd_mock = _mock_sd()
    with patch.dict("sys.modules", {"sounddevice": sd_mock}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/audio/devices")
    assert r.status_code == 200
    data = r.json()
    assert "devices" in data
    assert isinstance(data["devices"], list)


@pytest.mark.asyncio
async def test_list_devices_includes_defaults():
    sd_mock = _mock_sd(default=(18, 19))
    with patch.dict("sys.modules", {"sounddevice": sd_mock}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/audio/devices")
    data = r.json()
    assert "default_input" in data
    assert "default_output" in data
    assert data["default_input"] == 18
    assert data["default_output"] == 19


@pytest.mark.asyncio
async def test_list_devices_includes_configured():
    from core.config import update_config
    update_config(audio_input_device=3, audio_output_device=0)
    sd_mock = _mock_sd()
    with patch.dict("sys.modules", {"sounddevice": sd_mock}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/audio/devices")
    data = r.json()
    assert data["configured_input"] == 3
    assert data["configured_output"] == 0
    update_config(audio_input_device=None, audio_output_device=None)


@pytest.mark.asyncio
async def test_list_devices_each_has_index():
    sd_mock = _mock_sd()
    with patch.dict("sys.modules", {"sounddevice": sd_mock}):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/audio/devices")
    for dev in r.json()["devices"]:
        assert "index" in dev
        assert "name" in dev
        assert "input_channels" in dev
        assert "output_channels" in dev


# ── POST /api/audio/devices ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_devices_persists():
    from core.config import get_config, update_config
    update_config(audio_input_device=None, audio_output_device=None)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/audio/devices", json={"input_device": 18, "output_device": 0})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    cfg = get_config()
    assert cfg.audio_input_device == 18
    assert cfg.audio_output_device == 0
    update_config(audio_input_device=None, audio_output_device=None)


@pytest.mark.asyncio
async def test_set_devices_null_clears():
    from core.config import get_config, update_config
    update_config(audio_input_device=5, audio_output_device=5)
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/audio/devices", json={"input_device": None, "output_device": None})
    assert r.status_code == 200
    cfg = get_config()
    assert cfg.audio_input_device is None
    assert cfg.audio_output_device is None


@pytest.mark.asyncio
async def test_set_devices_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/audio/devices", json={"input_device": 1, "output_device": 1})
    assert r.json()["ok"] is True
    from core.config import update_config
    update_config(audio_input_device=None, audio_output_device=None)


# ── Config fields ─────────────────────────────────────────────────────────────

def test_config_defaults_none():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.audio_input_device is None
    assert cfg.audio_output_device is None


def test_config_persists_device_index(tmp_path, monkeypatch):
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_CONFIG_FILE", tmp_path / "cfg.json")
    monkeypatch.setattr(cfg_mod, "_config", cfg_mod.PliaConfig())
    cfg_mod.update_config(audio_input_device=7)
    cfg2 = cfg_mod.PliaConfig()
    cfg_mod._load_persisted(cfg2)
    assert cfg2.audio_input_device == 7
