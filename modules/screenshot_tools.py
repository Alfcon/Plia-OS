from __future__ import annotations
from core.registry import tool


@tool("Take a screenshot of the desktop. monitor=0 means all monitors combined, 1+ for a specific monitor.")
def take_screenshot(monitor: int = 0) -> str:
    try:
        import mss
        import mss.tools
    except ImportError:
        return "mss not installed. Run: pip install mss"

    from pathlib import Path
    from datetime import datetime
    from dashboard.server import UPLOADS_DIR

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(UPLOADS_DIR) / f"screenshot_{ts}.png"

    try:
        with mss.mss() as sct:
            mon = sct.monitors[monitor] if monitor < len(sct.monitors) else sct.monitors[0]
            img = sct.grab(mon)
            mss.tools.to_png(img.rgb, img.size, output=str(out))
    except Exception as exc:
        return f"Screenshot failed: {exc}"

    return f"Screenshot saved: {out.name} ({img.width}×{img.height})"
