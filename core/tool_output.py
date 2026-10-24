"""Live output from long-running tools to the dashboard chat.

A tool is a plain synchronous function run in a worker thread by
``core.registry.call_tool_async`` (``asyncio.to_thread``), where
``asyncio.get_running_loop()`` always raises — the same constraint
``core/watchdog.py`` documents. The main loop is therefore captured once at
startup and worker threads hand lines to it with ``run_coroutine_threadsafe``.

Lines are published as ``transcript`` events with role ``"tool"``: every
``core.events`` payload is forwarded to the dashboard WebSocket, and
``index.html`` renders it through ``_appendMsg``. That is the same channel
``/api/tools/run`` already uses for a tool's final result, so live progress and
the final answer appear in the same place.

Output is mirrored to a human-facing chat, not to a log: emissions are throttled
and capped so a chatty command such as nmap cannot flood the window. The full
captured output is still returned to the caller, so nothing is lost from the
tool's own result.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
import time

from core import events

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None

# Futures and tasks need a strong reference until they complete (asyncio docs).
_pending: set = set()

# Chat-facing limits.
_MIN_INTERVAL_S = 0.25          # at most ~4 mirrored lines per second
_MAX_LINES = 200                # per command
_MAX_LINE_CHARS = 400
_MAX_CAPTURED_CHARS = 200_000   # kept for the caller's own result


def capture_main_loop() -> None:
    """Remember the running loop. Call once from async startup (the lifespan)."""
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def _dispatch(coro) -> None:
    task = asyncio.ensure_future(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def emit_event(event_type: str, data: dict) -> None:
    """Emit an event from a worker thread (or the loop thread), never raising.

    Mirrors publish()'s loop handling so tools running under asyncio.to_thread
    can ask the dashboard for input/custom prompts.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _main_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            logger.debug("event dropped (no event loop): %s", event_type)
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(events.emit(event_type, data), loop)
        except RuntimeError:
            return
        _pending.add(fut)
        fut.add_done_callback(_pending.discard)
        return
    _dispatch(events.emit(event_type, data))


def publish(text: str, tool: str = "") -> None:
    """Mirror one line of tool output to the dashboard chat.

    Safe to call from a worker thread, and never raises: a missing or closed loop
    (early startup, a unit test, the app shutting down) simply drops the line.
    """
    if not text:
        return
    text = text[:_MAX_LINE_CHARS]
    payload = {"role": "tool", "text": f"[{tool}] {text}" if tool else text}
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _main_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            logger.debug("tool output dropped (no event loop): %s", text[:80])
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(events.emit("transcript", payload), loop)
        except RuntimeError:
            return
        _pending.add(fut)
        fut.add_done_callback(_pending.discard)
        return
    # Already on the loop thread.
    _dispatch(events.emit("transcript", payload))


def stream(
    cmd: list[str],
    *,
    tool: str = "",
    timeout: float = 120.0,
    stdin_text: str | None = None,
    max_lines: int = _MAX_LINES,
) -> subprocess.CompletedProcess:
    """Run ``cmd``, mirroring its output to the chat as it arrives.

    Returns a ``subprocess.CompletedProcess`` shaped like ``_run_timed``'s so it
    is a drop-in replacement. Unlike ``subprocess.run``, a timeout keeps the
    output produced up to that point instead of throwing it away — which is the
    difference between "timed out" and "timed out, here is what it found".
    """
    argv = list(cmd)
    started = time.monotonic()
    publish("$ " + " ".join(argv) + f"   (timeout {int(timeout)}s)", tool)
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_text is not None else None,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, -1, "", f"{argv[0]} not found")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, -1, "", str(exc))

    timed_out = threading.Event()

    def _kill() -> None:
        # Only claim a timeout when the process was still alive at the deadline.
        if proc.poll() is None:
            timed_out.set()
            try:
                proc.kill()
            except Exception:
                pass

    killer = threading.Timer(timeout, _kill)
    killer.daemon = True
    killer.start()

    captured: list[str] = []
    captured_chars = 0
    emitted = 0
    last_emit = 0.0
    try:
        if stdin_text is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\n")
            if captured_chars < _MAX_CAPTURED_CHARS:
                captured.append(line)
                captured_chars += len(line) + 1
            now = time.monotonic()
            if line.strip() and emitted < max_lines and (now - last_emit) >= _MIN_INTERVAL_S:
                publish(line, tool)
                emitted += 1
                last_emit = now
        proc.wait()
    finally:
        killer.cancel()
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass

    duration = time.monotonic() - started
    output = "\n".join(captured)
    if timed_out.is_set():
        publish(f"stopped after {int(timeout)}s (partial output kept)", tool)
        return subprocess.CompletedProcess(argv, -1, output, f"timed out after {int(timeout)}s")
    rc = proc.returncode if proc.returncode is not None else -1
    publish(f"finished (exit {rc}, {duration:.1f}s)", tool)
    return subprocess.CompletedProcess(argv, rc, output, "")


def tail(text: str, lines: int = 8) -> str:
    """The last ``lines`` non-empty lines of ``text`` — for a short chat summary."""
    kept = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join(kept[-lines:])
