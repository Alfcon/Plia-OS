# tests/test_vram_broker.py
import pytest
from unittest.mock import MagicMock, call
from voice.vram_broker import VRAMBroker, ModelEntry, get_vram_broker
import voice.vram_broker as broker_module


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
    light.load_fn.assert_called()  # restored
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
