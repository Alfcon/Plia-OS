from __future__ import annotations
import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_observer: "ObserverService | None" = None


def _find_keyboard() -> str | None:
    try:
        import evdev
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if evdev.ecodes.EV_KEY in caps:
                    keys = caps[evdev.ecodes.EV_KEY]
                    if evdev.ecodes.KEY_A in keys and evdev.ecodes.KEY_SPACE in keys:
                        return dev.path
            except Exception:
                pass
    except ImportError:
        pass
    return None


def _keycode_to_char(code: int, shift: bool) -> str:
    try:
        from evdev import ecodes as e
        _MAP: dict[int, tuple[str, str]] = {
            e.KEY_A: ("a", "A"), e.KEY_B: ("b", "B"), e.KEY_C: ("c", "C"),
            e.KEY_D: ("d", "D"), e.KEY_E: ("e", "E"), e.KEY_F: ("f", "F"),
            e.KEY_G: ("g", "G"), e.KEY_H: ("h", "H"), e.KEY_I: ("i", "I"),
            e.KEY_J: ("j", "J"), e.KEY_K: ("k", "K"), e.KEY_L: ("l", "L"),
            e.KEY_M: ("m", "M"), e.KEY_N: ("n", "N"), e.KEY_O: ("o", "O"),
            e.KEY_P: ("p", "P"), e.KEY_Q: ("q", "Q"), e.KEY_R: ("r", "R"),
            e.KEY_S: ("s", "S"), e.KEY_T: ("t", "T"), e.KEY_U: ("u", "U"),
            e.KEY_V: ("v", "V"), e.KEY_W: ("w", "W"), e.KEY_X: ("x", "X"),
            e.KEY_Y: ("y", "Y"), e.KEY_Z: ("z", "Z"),
            e.KEY_0: ("0", ")"), e.KEY_1: ("1", "!"), e.KEY_2: ("2", "@"),
            e.KEY_3: ("3", "#"), e.KEY_4: ("4", "$"), e.KEY_5: ("5", "%"),
            e.KEY_6: ("6", "^"), e.KEY_7: ("7", "&"), e.KEY_8: ("8", "*"),
            e.KEY_9: ("9", "("),
            e.KEY_SPACE: (" ", " "), e.KEY_ENTER: ("\n", "\n"),
            e.KEY_BACKSPACE: ("\b", "\b"),
            e.KEY_MINUS: ("-", "_"), e.KEY_EQUAL: ("=", "+"),
            e.KEY_COMMA: (",", "<"), e.KEY_DOT: (".", ">"),
            e.KEY_SLASH: ("/", "?"), e.KEY_SEMICOLON: (";", ":"),
            e.KEY_APOSTROPHE: ("'", '"'),
        }
        pair = _MAP.get(code)
        return (pair[1] if shift else pair[0]) if pair else ""
    except ImportError:
        return ""


class ObserverService:
    def __init__(self) -> None:
        from agents.observer_store import get_observer_store
        from core.config import get_config
        self._store = get_observer_store()
        cfg = get_config()
        self._screen_interval: int = cfg.observer_screen_interval
        self._profile_interval: int = cfg.observer_profile_interval
        self._profile_text: str = ""
        self._last_capture_ts: str | None = None
        self._last_profile_ts: str | None = None
        self._current_window: str | None = None
        self._current_app: str | None = None
        self._last_ocr_text: str = ""
        self._tasks: list[asyncio.Task] = []
        saved = self._store.get_latest_profile()
        if saved:
            self._profile_text = saved

    async def start(self) -> None:
        from core.config import get_config
        cfg = get_config()
        await asyncio.to_thread(self._store.prune_old, cfg.observer_retention_hours)
        self._tasks = [
            asyncio.create_task(self._screen_loop()),
            asyncio.create_task(self._focus_loop()),
            asyncio.create_task(self._key_loop()),
            asyncio.create_task(self._profile_loop()),
        ]
        logger.info("Observer started")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        logger.info("Observer stopped")

    def get_profile(self) -> str:
        return self._profile_text

    def is_running(self) -> bool:
        return bool(self._tasks) and any(not t.done() for t in self._tasks)

    def last_capture_ts(self) -> str | None:
        return self._last_capture_ts

    def last_profile_ts(self) -> str | None:
        return self._last_profile_ts

    async def _screen_loop(self) -> None:
        try:
            import mss
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.warning("mss or pytesseract not installed; screen capture disabled")
            return

        while True:
            try:
                await asyncio.sleep(self._screen_interval)

                def _capture() -> str:
                    with mss.mss() as sct:
                        shot = sct.grab(sct.monitors[0])
                        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                        return pytesseract.image_to_string(img)

                text = await asyncio.to_thread(_capture)
                text = text.strip()
                if not text or text == self._last_ocr_text:
                    continue
                self._last_ocr_text = text
                ts = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    self._store.add_screen_obs,
                    ts, self._current_window, self._current_app, text,
                )
                self._last_capture_ts = ts
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Screen capture error")

    async def _focus_loop(self) -> None:
        prev_window: str | None = None
        prev_app: str | None = None
        focus_start = asyncio.get_event_loop().time()

        while True:
            try:
                await asyncio.sleep(2.0)

                def _get_focus() -> tuple[str, str]:
                    r = subprocess.run(
                        ["xdotool", "getactivewindow", "getwindowname"],
                        capture_output=True, text=True, timeout=2,
                    )
                    title = r.stdout.strip() if r.returncode == 0 else "unknown"
                    r2 = subprocess.run(
                        ["xdotool", "getactivewindow", "getwindowpid"],
                        capture_output=True, text=True, timeout=2,
                    )
                    app = "unknown"
                    if r2.returncode == 0:
                        pid = r2.stdout.strip()
                        try:
                            app = Path(f"/proc/{pid}/comm").read_text().strip()
                        except Exception:
                            pass
                    return title, app

                title, app = await asyncio.to_thread(_get_focus)
                self._current_window = title
                self._current_app = app

                if title != prev_window:
                    if prev_window is not None:
                        elapsed = asyncio.get_event_loop().time() - focus_start
                        ts = datetime.now(timezone.utc).isoformat()
                        await asyncio.to_thread(
                            self._store.add_focus_event,
                            ts, prev_window, prev_app, elapsed,
                        )
                    prev_window = title
                    prev_app = app
                    focus_start = asyncio.get_event_loop().time()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Focus tracking error")

    async def _key_loop(self) -> None:
        try:
            import evdev
        except ImportError:
            logger.warning("python-evdev not installed; keystroke capture disabled")
            return

        path = _find_keyboard()
        if path is None:
            logger.warning("No keyboard device found; keystroke capture disabled")
            return

        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            logger.warning(
                "Permission denied for %s — add user to input group: "
                "sudo usermod -aG input $USER", path
            )
            return

        buffer: list[str] = []
        last_flush = asyncio.get_event_loop().time()
        shift_held = False
        FLUSH_INTERVAL = 10.0

        try:
            async for event in dev.async_read_loop():
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                key_event = evdev.categorize(event)
                code = key_event.scancode
                if key_event.keystate == evdev.KeyEvent.key_down:
                    if code in (evdev.ecodes.KEY_LEFTSHIFT, evdev.ecodes.KEY_RIGHTSHIFT):
                        shift_held = True
                        continue
                    char = _keycode_to_char(code, shift_held)
                    if char:
                        buffer.append(char)
                elif key_event.keystate == evdev.KeyEvent.key_up:
                    if code in (evdev.ecodes.KEY_LEFTSHIFT, evdev.ecodes.KEY_RIGHTSHIFT):
                        shift_held = False

                now = asyncio.get_event_loop().time()
                if now - last_flush >= FLUSH_INTERVAL and buffer:
                    chunk = "".join(buffer)
                    buffer.clear()
                    last_flush = now
                    ts = datetime.now(timezone.utc).isoformat()
                    await asyncio.to_thread(
                        self._store.add_key_chunk,
                        ts, self._current_window, self._current_app, chunk,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Keystroke capture error")

    async def _run_profile_once(self) -> None:
        try:
            obs = await asyncio.to_thread(self._store.get_recent_obs, 10)
            screen_snippets = "\n".join(
                f"[{o['ts'][:19]}] {o['window_title']}: {o['ocr_text'][:200]}"
                for o in obs["screen"]
            ) or "no screen data"
            focus_summary = ", ".join(
                f"{o['app_name']} ({o['duration_seconds']:.0f}s)"
                for o in obs["focus"]
            ) or "no focus data"
            key_snippets = "\n".join(
                f"[{o['app_name']}]: {o['text_chunk'][:100]}"
                for o in obs["keys"]
            ) or "no keystroke data"

            prompt = (
                "You are summarizing a user's recent computer activity to help "
                "an AI assistant understand them better.\n\n"
                f"Recent activity (last 10 minutes):\n"
                f"SCREEN (30s intervals):\n{screen_snippets}\n\n"
                f"FOCUS: {focus_summary}\n\n"
                f"TYPED:\n{key_snippets}\n\n"
                "Write a 3-5 sentence profile update describing:\n"
                "- What the user is working on right now\n"
                "- What apps/sites they are using\n"
                "- Any notable patterns or context useful for an AI assistant\n\n"
                "Be concise and factual. No speculation beyond what the data shows."
            )
            from agents.llm import call_llm
            msg = await call_llm([
                {"role": "system", "content": "You are a concise activity summarizer."},
                {"role": "user", "content": prompt},
            ])
            profile_text = (msg.get("content") or "").strip()
            if profile_text:
                ts = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(self._store.save_profile, ts, profile_text)
                self._profile_text = profile_text
                self._last_profile_ts = ts
                from core import events
                await events.emit("observer_status", {
                    "enabled": True,
                    "running": True,
                    "last_capture": self._last_capture_ts,
                    "last_profile": self._last_profile_ts,
                    "profile_preview": profile_text[:200],
                })
        except Exception:
            logger.exception("Profile build error")

    async def _profile_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._profile_interval)
                await self._run_profile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Profile loop error")


def get_observer() -> ObserverService:
    global _observer
    if _observer is None:
        _observer = ObserverService()
    return _observer
