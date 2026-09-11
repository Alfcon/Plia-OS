"""Register the Ollama server's resident model with the VRAM broker.

Ollama runs as a separate process, so the broker cannot free its VRAM with
torch — eviction is done by asking Ollama to unload via ``keep_alive: 0``.
Loading is left to Ollama itself: it lazy-loads the model on the next chat
request, so load_fn is a no-op and call_llm reports residency back to the
broker with notify_active("ollama").
"""
from __future__ import annotations

import logging

import httpx

from voice.vram_broker import ModelEntry, get_vram_broker

logger = logging.getLogger(__name__)

# Rough footprint of a typical 7-8B quantised model; only used for the
# dashboard display, not for eviction decisions.
OLLAMA_VRAM_GB = 4.0
_UNLOAD_TIMEOUT = 10.0


def _unload() -> None:
    from core.config import get_config
    config = get_config()
    try:
        httpx.post(
            f"{config.ollama_url}/api/generate",
            json={"model": config.ollama_model, "keep_alive": 0},
            timeout=_UNLOAD_TIMEOUT,
        )
    except httpx.ConnectError:
        # Server not running → model is not in VRAM; nothing to unload.
        logger.info("Ollama not reachable at %s — nothing to unload", config.ollama_url)
    except Exception:
        logger.warning("Could not ask Ollama to unload %r", config.ollama_model, exc_info=True)


def _load() -> None:
    # Ollama reloads the model on the next /api/chat call; forcing a warm-up
    # here would block the broker lock for the whole model load.
    pass


def register_ollama() -> None:
    get_vram_broker().register(ModelEntry(
        name="ollama",
        priority=2,
        vram_gb=OLLAMA_VRAM_GB,
        load_fn=_load,
        unload_fn=_unload,
        # Assume resident: an unload request for a model that is not actually
        # loaded is a harmless no-op, whereas assuming "unloaded" would hide
        # Ollama from eviction until the first chat turn.
        state="gpu",
    ))
