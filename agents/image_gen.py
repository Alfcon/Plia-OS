from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

from voice.vram_broker import get_vram_broker, ModelEntry

logger = logging.getLogger(__name__)

_MODEL_ID = "runwayml/stable-diffusion-v1-5"
_pipe = None


def _available() -> bool:
    try:
        import torch
        import diffusers  # noqa: F401
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _output_dir() -> Path:
    from core.config import get_config
    d = Path(get_config().memory_dir) / "generated"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s or "image")[:40]


def _load_pipe() -> None:
    global _pipe
    _pipe = None
    try:
        import torch
        from diffusers import StableDiffusionPipeline
        _pipe = StableDiffusionPipeline.from_pretrained(_MODEL_ID, torch_dtype=torch.float16).to("cuda")
    except Exception:
        logger.exception("Stable Diffusion pipeline load failed")


def _free_pipe() -> None:
    global _pipe
    _pipe = None
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def _ensure_registered() -> None:
    get_vram_broker().register(
        ModelEntry(
            name="image_gen",
            priority=3,
            vram_gb=4.0,
            load_fn=_load_pipe,
            unload_fn=_free_pipe,
        )
    )


def generate_image(prompt: str, steps: int = 25) -> str:
    """Generate an image locally via Stable Diffusion. Never raises."""
    if not _available():
        return "Image generation needs a CUDA GPU with diffusers installed; not available here."
    _ensure_registered()
    broker = get_vram_broker()
    try:
        broker.request("image_gen")
    except Exception as exc:
        logger.exception("Image model load failed")
        return f"Image generation failed to load model: {exc}"
    try:
        if _pipe is None:
            return "Image generation failed: pipeline did not load."
        image = _pipe(prompt, num_inference_steps=steps).images[0]
        path = _output_dir() / f"img_{_slug(prompt)}_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
        image.save(path)
        return f"Saved image to `{path}`."
    except Exception as exc:
        logger.exception("Image generation failed")
        return f"Image generation failed: {exc}"
    finally:
        broker.release("image_gen")
