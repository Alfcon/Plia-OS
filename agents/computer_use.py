from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _xdotool_available() -> bool:
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return False
    return shutil.which("xdotool") is not None


def _screen_size() -> tuple[int, int]:
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(mon["width"]), int(mon["height"])
    except Exception:
        return 0, 0


def _clamp(v: int, hi: int) -> int:
    return max(0, min(v, hi - 1)) if hi > 0 else v


def _run_action(action: dict, screen: tuple[int, int]) -> str:
    if not isinstance(action, dict):
        return "Invalid action (not a dict)"
    a = action.get("action", "")
    w, h = screen
    try:
        if a in ("click", "double_click"):
            x = _clamp(int(action.get("x", 0)), w)
            y = _clamp(int(action.get("y", 0)), h)
            repeat = ["--repeat", "2"] if a == "double_click" else []
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y), "click", *repeat, "1"],
                check=True, capture_output=True, timeout=10,
            )
            return f"{a} at ({x},{y})"
        if a == "type":
            text = str(action.get("text", ""))
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--", text],
                check=True, capture_output=True, timeout=10,
            )
            return f"typed {len(text)} chars"
        if a == "key":
            name = str(action.get("name", ""))
            if not name:
                return "key: missing name"
            subprocess.run(["xdotool", "key", "--", name], check=True, capture_output=True, timeout=10)
            return f"key {name}"
        if a == "scroll":
            direction = str(action.get("direction", "down"))
            amount = max(1, int(action.get("amount", 3)))
            button = "4" if direction == "up" else "5"
            for _ in range(amount):
                subprocess.run(["xdotool", "click", button], check=True, capture_output=True, timeout=10)
            return f"scroll {direction} {amount}"
        if a == "done":
            return f"DONE: {action.get('summary', '')}"
        return f"Unknown action: {a}"
    except subprocess.TimeoutExpired:
        return f"Action '{a}' timed out"
    except Exception as exc:
        return f"Action '{a}' failed: {exc}"


def _parse_action(text: str) -> dict | None:
    if not isinstance(text, str):
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


_MAX_STEPS_CAP = 50

_SCHEMA = (
    "Reply with ONE JSON action and nothing else. Actions:\n"
    '{"action":"click","x":<int>,"y":<int>}\n'
    '{"action":"double_click","x":<int>,"y":<int>}\n'
    '{"action":"type","text":"<text>"}\n'
    '{"action":"key","name":"<xdotool keyname, e.g. Return, ctrl+s, Escape>"}\n'
    '{"action":"scroll","direction":"up|down","amount":<int>}\n'
    '{"action":"done","summary":"<what was accomplished>"}'
)


async def run_computer_use(goal: str, max_steps: int = 15) -> str:
    import asyncio
    from agents.vision import describe_image_bytes
    from modules.vision_tools import _screen_png
    from core import events

    if not _xdotool_available():
        return "Computer control needs xdotool on X11. Install xdotool and run on an X11 session."

    steps = max(1, min(int(max_steps), _MAX_STEPS_CAP))
    screen = _screen_size()
    history: list[str] = []

    for i in range(steps):
        png = _screen_png(0)
        if png is None:
            history.append("could not capture screen")
            break
        hist = "\n".join(history[-8:]) if history else "(none yet)"
        prompt = (
            f"You control a desktop to accomplish this goal: {goal}\n"
            f"Screen size: {screen[0]}x{screen[1]} pixels.\n"
            f"Actions so far:\n{hist}\n\n{_SCHEMA}"
        )
        reply = await describe_image_bytes(png, prompt)
        action = _parse_action(reply)
        if action is None:
            history.append(f"could not parse action from: {reply[:120]}")
            break
        await events.emit("computer_action", {"step": i, "action": action})
        result = await asyncio.to_thread(_run_action, action, screen)
        history.append(f"step {i}: {action.get('action', '?')} -> {result}")
        if result.startswith("DONE:"):
            break

    return f"Goal: {goal}\nSteps ({len(history)}):\n" + "\n".join(history)
