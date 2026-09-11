from __future__ import annotations

from pathlib import Path

from core.registry import tool


def _screen_png(monitor: int = 0) -> bytes | None:
    try:
        import mss
        import mss.tools
    except ImportError:
        return None
    try:
        with mss.mss() as sct:
            mon = sct.monitors[monitor] if 0 <= monitor < len(sct.monitors) else sct.monitors[0]
            img = sct.grab(mon)
            return mss.tools.to_png(img.rgb, img.size)
    except Exception:
        return None


@tool(
    "Describe or answer a question about an image file using the local vision model. "
    "image_path: path to a PNG/JPG. question: what to ask (default: describe it in detail). "
    "Requires a vision_model set in config (e.g. 'llava')."
)
async def describe_image(image_path: str, question: str = "Describe this image in detail.") -> str:
    from agents.vision import describe_image_bytes
    p = Path(image_path).expanduser()
    if not p.is_file():
        return f"No file at '{image_path}'."
    try:
        data = p.read_bytes()
    except OSError as exc:
        return f"Could not read '{image_path}': {exc}"
    return await describe_image_bytes(data, question)


@tool(
    "Look at the current screen and answer a question about it using the local vision model. "
    "question: what to ask (default: describe the screen). monitor: 0 = all monitors, 1+ = a specific one. "
    "Requires a vision_model set in config (e.g. 'llava')."
)
async def look_at_screen(question: str = "Describe what is on the screen.", monitor: int = 0) -> str:
    from agents.vision import describe_image_bytes
    png = _screen_png(monitor)
    if png is None:
        return "Could not capture the screen (is mss installed?)."
    return await describe_image_bytes(png, question)
