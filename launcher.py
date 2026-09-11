#!/usr/bin/env python3
"""
Plia-OS launcher with optional system tray support.

Usage:
    python launcher.py [--preset <name>] [--no-tray] [--host HOST] [--port PORT]

Optional extras:
    pip install -e ".[tray]"   # enables system tray icon (pystray + pillow)
"""
from __future__ import annotations
import argparse
import sys
import threading
import time
import webbrowser


def _run_server(host: str, port: int) -> None:
    import uvicorn
    from core.main import create_app
    cfg = uvicorn.Config(create_app(), host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    server.run()


def _make_tray_icon():
    """Return a simple blue circle PIL Image."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill="#3b82f6", outline="#1d4ed8", width=3)
    d.ellipse((22, 22, 42, 42), fill="#ffffff")
    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="Plia-OS launcher")
    parser.add_argument("--preset", metavar="NAME", help="Apply a saved config preset before start")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    parser.add_argument("--host", default=None, help="Override listen host")
    parser.add_argument("--port", type=int, default=None, help="Override listen port")
    args = parser.parse_args()

    if args.preset:
        from core.preset_store import apply_preset
        if not apply_preset(args.preset):
            print(f"Unknown preset: {args.preset!r}", file=sys.stderr)
            sys.exit(1)
        print(f"Applied preset: {args.preset}")

    from core.config import get_config
    cfg = get_config()
    host = args.host or cfg.host
    port = args.port or cfg.port
    url = f"http://{host}:{port}"

    server_thread = threading.Thread(target=_run_server, args=(host, port), daemon=True)
    server_thread.start()

    if not args.no_tray:
        try:
            import pystray

            def _open(icon, item):  # noqa: ARG001
                webbrowser.open(url)

            def _stop(icon, item):  # noqa: ARG001
                icon.stop()

            icon = pystray.Icon(
                "plia-os",
                _make_tray_icon(),
                "Plia-OS",
                menu=pystray.Menu(
                    pystray.MenuItem("Open Dashboard", _open, default=True),
                    pystray.MenuItem("Quit", _stop),
                ),
            )
            time.sleep(1.5)
            webbrowser.open(url)
            icon.run()
            return
        except ImportError:
            print("pystray not installed; running without tray icon (pip install -e '[.tray]')")

    time.sleep(1.5)
    webbrowser.open(url)
    print(f"Plia-OS running at {url}  (Ctrl-C to stop)")
    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
