from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 120.0


async def describe_image_bytes(image_bytes: bytes, prompt: str) -> str:
    """Send an image + prompt to the local Ollama vision model, return the reply.
    Defensive: returns a message string on any failure, never raises."""
    from core.config import get_config
    config = get_config()
    model = config.vision_model
    if not model:
        return "No vision model set. Set config.vision_model (e.g. 'llava') and run: ollama pull llava"
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{config.ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else None
        if code == 404:
            return f"Vision model '{model}' not found. Run: ollama pull {model}"
        return f"Vision error: HTTP {code}"
    except httpx.TimeoutException:
        return "Vision model timed out."
    except Exception as exc:
        logger.warning("Vision request failed: %s", exc)
        return f"Vision error: {type(exc).__name__}"
