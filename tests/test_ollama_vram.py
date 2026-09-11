# tests/test_ollama_vram.py
import httpx
import pytest
import respx
from unittest.mock import MagicMock

import voice.vram_broker as broker_module
from voice.vram_broker import VRAMBroker, ModelEntry, get_vram_broker
from core.config import update_config


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


# --- VRAMBroker.notify_active ---

def test_notify_active_marks_gpu_without_loading():
    b = VRAMBroker()
    e = _make_entry("ollama", 2)
    b.register(e)
    b.notify_active("ollama")
    assert e.state == "gpu"
    e.load_fn.assert_not_called()


def test_notify_active_does_not_evict_others():
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    e = _make_entry("ollama", 2)
    b.register(light)
    b.register(e)
    b.request("kokoro")
    b.notify_active("ollama")
    light.unload_fn.assert_not_called()
    assert light.state == "gpu"


def test_notify_active_unregistered_is_noop():
    b = VRAMBroker()
    b.notify_active("nonexistent")  # must not raise


# --- register_ollama ---

def test_register_ollama_registers_priority2_entry_assumed_resident():
    from agents.ollama_vram import register_ollama
    register_ollama()
    entry = get_vram_broker()._models["ollama"]
    assert entry.priority == 2
    assert entry.state == "gpu"


def test_register_ollama_idempotent():
    from agents.ollama_vram import register_ollama
    register_ollama()
    register_ollama()
    assert list(get_vram_broker()._models).count("ollama") == 1


@respx.mock
def test_unload_posts_keep_alive_zero():
    from agents.ollama_vram import register_ollama
    update_config(ollama_url="http://ollama.test:11434", ollama_model="llama3")
    route = respx.post("http://ollama.test:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"done": True})
    )
    register_ollama()
    get_vram_broker()._models["ollama"].unload_fn()
    assert route.called
    import json
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "llama3"
    assert body["keep_alive"] == 0


@respx.mock
def test_unload_survives_ollama_down():
    from agents.ollama_vram import register_ollama
    update_config(ollama_url="http://ollama.test:11434")
    respx.post("http://ollama.test:11434/api/generate").mock(
        side_effect=httpx.ConnectError("refused")
    )
    register_ollama()
    get_vram_broker()._models["ollama"].unload_fn()  # must not raise


@respx.mock
def test_load_fn_is_noop_no_http():
    # respx with no registered routes fails any request — load_fn must make none
    from agents.ollama_vram import register_ollama
    register_ollama()
    get_vram_broker()._models["ollama"].load_fn()


# --- broker integration ---

@respx.mock
def test_heavy_request_evicts_ollama_via_keep_alive_zero():
    from agents.ollama_vram import register_ollama
    update_config(ollama_url="http://ollama.test:11434", ollama_model="llama3")
    route = respx.post("http://ollama.test:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"done": True})
    )
    register_ollama()
    b = get_vram_broker()
    heavy = _make_entry("dramabox", 3, vram_gb=8.5)
    b.register(heavy)
    b.request("dramabox")
    assert route.called
    assert b._models["ollama"].state == "unloaded"
    assert heavy.state == "gpu"


@respx.mock
def test_release_heavy_restores_ollama_state():
    from agents.ollama_vram import register_ollama
    update_config(ollama_url="http://ollama.test:11434", ollama_model="llama3")
    respx.post("http://ollama.test:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"done": True})
    )
    register_ollama()
    b = get_vram_broker()
    heavy = _make_entry("dramabox", 3, vram_gb=8.5)
    b.register(heavy)
    b.request("dramabox")
    b.release("dramabox")
    assert b._models["ollama"].state == "gpu"


# --- startup wiring ---

def test_create_app_registers_ollama():
    from core.main import create_app
    create_app()
    assert "ollama" in get_vram_broker()._models


# --- call_llm wiring ---

@respx.mock
async def test_call_llm_notifies_broker_ollama_active():
    from agents.ollama_vram import register_ollama
    from agents.llm import call_llm
    update_config(ollama_url="http://ollama.test:11434", ollama_model="llama3")
    respx.post("http://ollama.test:11434/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": "hi"}}
        )
    )
    register_ollama()
    entry = get_vram_broker()._models["ollama"]
    entry.state = "unloaded"  # simulate prior eviction; Ollama lazy-reloads on this call
    await call_llm([{"role": "user", "content": "hello"}])
    assert entry.state == "gpu"


@respx.mock
async def test_call_llm_works_without_registration():
    # e.g. unit contexts that never ran create_app — notify must be a no-op
    from agents.llm import call_llm
    update_config(ollama_url="http://ollama.test:11434", ollama_model="llama3")
    respx.post("http://ollama.test:11434/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": "hi"}}
        )
    )
    result = await call_llm([{"role": "user", "content": "hello"}])
    assert result["content"] == "hi"
