from __future__ import annotations

import asyncio
import io
import logging
from typing import Literal
import os
import shutil
from pathlib import Path

from core.registry import tool
from agents.vision import describe_image_bytes
from modules.vision_tools import _screen_png

logger = logging.getLogger(__name__)

_ENGINES = {"auto", "tesseract", "vision"}
_VISION_PROMPT = (
    "Transcribe ALL visible text in this image exactly and verbatim. "
    "Output only the text, with no commentary, headings, or description."
)


def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


def _run_tesseract(image_bytes: bytes) -> str:
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img).strip()


async def _ocr(image_bytes: bytes, engine: str) -> tuple[str, str]:
    """Return (text, used). used ∈ tesseract|vision|none|no_tesseract. Never raises."""
    if engine != "vision":
        if _tesseract_available():
            try:
                text = await asyncio.to_thread(_run_tesseract, image_bytes)
            except Exception:
                logger.debug("tesseract failed", exc_info=True)
                text = ""
            if text:
                return (text, "tesseract")
            if engine == "tesseract":
                return ("", "none")
            # engine == "auto" → fall through to vision
        elif engine == "tesseract":
            return ("", "no_tesseract")
        # engine == "auto" and tesseract unavailable → fall through to vision
    try:
        text = (await describe_image_bytes(image_bytes, _VISION_PROMPT) or "").strip()
    except Exception:
        logger.debug("vision ocr failed", exc_info=True)
        return ("", "none")
    return (text, "vision") if text else ("", "none")


def _render(text: str, used: str) -> str:
    if used == "no_tesseract":
        return ("Tesseract OCR is not installed. Install it (e.g. `sudo apt install "
                "tesseract-ocr`) or use engine='vision'.")
    if used == "none" or not text:
        return "No text found."
    return f"[{used}]\n{text}"


@tool(
    "Extract text from an image file using OCR. engine: 'auto' (Tesseract, falling back to the "
    "vision model if it finds no text), 'tesseract' (exact/offline), or 'vision' (LLM vision "
    "model — better for messy/handwritten text)."
)
async def extract_text_from_image(image_path: str, engine: Literal["auto", "tesseract", "vision"] = "auto") -> str:
    engine = engine if engine in _ENGINES else "auto"
    if not os.path.isfile(image_path):
        return f"Image not found: {image_path}"
    try:
        data = Path(image_path).read_bytes()
    except OSError as exc:
        return f"Could not read image: {exc}"
    text, used = await _ocr(data, engine)
    return _render(text, used)


@tool(
    "Extract text visible on the screen using OCR. monitor=0 = all monitors, 1+ = a specific "
    "monitor. engine: 'auto' (Tesseract with vision fallback), 'tesseract', or 'vision'."
)
async def extract_text_from_screen(monitor: int = 0, engine: Literal["auto", "tesseract", "vision"] = "auto") -> str:
    engine = engine if engine in _ENGINES else "auto"
    png = _screen_png(monitor)
    if png is None:
        return "Could not capture the screen (no display or mss unavailable)."
    text, used = await _ocr(png, engine)
    return _render(text, used)
