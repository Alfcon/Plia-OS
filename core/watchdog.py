"""
Watchdog registry: lifecycle control for background asyncio tasks.

States: running | paused | stopped. Pause closes a gate each loop awaits at
the top of its iteration; stop cancels the task (or awaits a custom stop_fn
for service entries). Paused/stopped states persist to config and are applied
by spawn() at startup.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

VALID_STATES = ("running", "paused", "stopped")

_pending_reactivations: dict[str, str] = {}  # pending_id -> task name
_REACTIVATION_TTL_S = 60.0

# The event loop the app (or the current test) is running on. Sync @tool
# functions are dispatched via asyncio.to_thread by core.registry.call_tool_async,
# so asyncio.get_running_loop() inside them always raises RuntimeError — we
# capture the loop here (whenever register()/spawn() runs with one active) so
# reactivation_warning can still schedule work onto it from a worker thread.
_main_loop: asyncio.AbstractEventLoop | None = None

# Strong refs to fire-and-forget reactivation tasks/futures so nothing gets
# GC'd mid-flight (asyncio.Task and concurrent.futures.Future both need a
# saved reference per the asyncio docs).
_pending_tasks: set = set()


def _capture_main_loop() -> None:
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def _track_task(task) -> None:
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


class _Entry:
    def __init__(self, factory, description: str, stop_fn=None, is_running_fn=None):
        self.factory = factory
        self.description = description
        self.stop_fn = stop_fn
        self.is_running_fn = is_running_fn
        self.task: asyncio.Task | None = None
        self.state: str = "running"
        self.gate = asyncio.Event()
        self.gate.set()


_registry: dict[str, _Entry] = {}


def register(name: str, factory, description: str = "", stop_fn=None, is_running_fn=None) -> None:
    _registry[name] = _Entry(factory, description, stop_fn, is_running_fn)
    _capture_main_loop()


def get_entry(name: str) -> _Entry | None:
    return _registry.get(name)


def names() -> list[str]:
    return list(_registry)


def set_task(name: str, task: asyncio.Task) -> None:
    entry = _registry.get(name)
    if entry is not None:
        entry.task = task


def _get(name: str) -> _Entry:
    entry = _registry.get(name)
    if entry is None:
        raise KeyError(f"No registered watchdog task '{name}'")
    return entry


async def watchdog_gate(name: str) -> None:
    entry = _registry.get(name)
    if entry is None:
        return
    await entry.gate.wait()


def _persist(name: str, state: str) -> None:
    from core.config import get_config, update_config
    states = dict(get_config().watchdog_task_states or {})
    if state == "running":
        if name not in states:
            return
        states.pop(name)
    else:
        states[name] = state
    update_config(watchdog_task_states=states)


def is_running(name: str) -> bool:
    entry = _registry.get(name)
    if entry is None:
        return False
    if entry.state != "running":
        return False
    if entry.is_running_fn is not None:
        return bool(entry.is_running_fn())
    return bool(entry.task and not entry.task.done())


def status() -> dict:
    return {
        name: {
            "state": entry.state,
            "running": is_running(name),
            "description": entry.description,
        }
        for name, entry in _registry.items()
    }


def is_paused(name: str) -> bool:
    """True if the named task's gate is currently closed (paused)."""
    entry = _registry.get(name)
    if entry is None:
        return False
    return not entry.gate.is_set()


async def pause(name: str) -> None:
    """Legal only from 'running'. Raises ValueError from 'paused' or 'stopped'."""
    entry = _get(name)
    if entry.state != "running":
        raise ValueError(f"Cannot pause '{name}': not running (state={entry.state!r})")
    entry.gate.clear()
    entry.state = "paused"
    await asyncio.to_thread(_persist, name, "paused")


async def resume(name: str) -> None:
    """Legal only from 'paused'. Raises ValueError from 'running' or 'stopped'
    (in particular, a stopped entry's state/gate is left untouched)."""
    entry = _get(name)
    if entry.state != "paused":
        raise ValueError(f"Cannot resume '{name}': not paused (state={entry.state!r})")
    entry.gate.set()
    entry.state = "running"
    await asyncio.to_thread(_persist, name, "running")


async def _cancel_entry(entry: _Entry) -> None:
    # Skip stop_fn if already stopped with no live task (no-op for side effects)
    task = entry.task
    is_already_stopped = entry.state == "stopped" and (task is None or task.done())

    if entry.stop_fn is not None and not is_already_stopped:
        try:
            await entry.stop_fn()
        except Exception:
            logger.exception("Watchdog stop_fn failed")

    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass


async def stop(name: str) -> None:
    entry = _get(name)
    await _cancel_entry(entry)
    entry.state = "stopped"
    entry.gate.set()  # never leave a future task wedged on a closed gate
    await asyncio.to_thread(_persist, name, "stopped")


async def restart(name: str) -> asyncio.Task:
    entry = _get(name)
    await _cancel_entry(entry)
    entry.gate.set()
    new_task = asyncio.create_task(entry.factory(), name=name)
    entry.task = new_task
    entry.state = "running"
    await asyncio.to_thread(_persist, name, "running")
    return new_task


async def reactivate(name: str) -> None:
    entry = _get(name)
    if entry.state == "paused":
        await resume(name)
    elif entry.state == "stopped":
        await restart(name)


async def request_reactivation(name: str, reason: str) -> str | None:
    entry = _registry.get(name)
    if entry is None or entry.state == "running":
        return None
    pending_id = str(uuid.uuid4())
    _pending_reactivations[pending_id] = name
    try:
        from core import events
        await events.emit("watchdog_reactivate_request", {
            "id": pending_id,
            "task": name,
            "state": entry.state,
            "reason": reason,
        })
    except Exception:
        logger.exception("Failed to emit watchdog_reactivate_request for %s", name)
        _pending_reactivations.pop(pending_id, None)
        return None
    asyncio.get_running_loop().call_later(
        _REACTIVATION_TTL_S, _pending_reactivations.pop, pending_id, None
    )
    return pending_id


def respond_reactivation(pending_id: str) -> str | None:
    return _pending_reactivations.pop(pending_id, None)


def reactivation_warning(name: str, reason: str) -> str:
    """Non-blocking. Empty string when the task is running; otherwise attempts
    to fire a dashboard reactivation prompt and returns a warning for the
    caller's reply.

    Sync @tool functions run inside asyncio.to_thread() worker threads (see
    core.registry.call_tool_async), so get_running_loop() there always raises
    RuntimeError — fall back to scheduling onto the captured main loop via
    run_coroutine_threadsafe. If neither is available, log it and return a
    warning that does NOT claim a dashboard prompt was raised.
    """
    entry = _registry.get(name)
    if entry is None or entry.state == "running":
        return ""

    scheduled = False
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            request_reactivation(name, reason), name=f"reactivate_prompt_{name}"
        )
        _track_task(task)
        scheduled = True
    except RuntimeError:
        # No running loop in this thread — try the captured main loop.
        if _main_loop is not None and not _main_loop.is_closed() and _main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(request_reactivation(name, reason), _main_loop)
            _track_task(fut)
            scheduled = True
        else:
            logger.warning(
                "reactivation_warning: no event loop available to request "
                "reactivation for %r — dashboard prompt not raised", name
            )

    if scheduled:
        return (
            f" Note: {name} is {entry.state} — approve the dashboard prompt to "
            f"reactivate it, otherwise this won't fire."
        )
    return (
        f" Note: {name} is {entry.state} — reactivate it from the dashboard "
        f"Watchdog panel, otherwise this won't fire."
    )


def clear_state(name: str) -> None:
    """Sync: mark running and drop any persisted entry (used by enable paths).

    Thread-safe: called from sync @tool functions (modules/observer_tools.py,
    modules/proactive_tools.py) that run inside asyncio.to_thread() worker
    threads (see core.registry.call_tool_async), where get_running_loop()
    always raises RuntimeError. In that case, mutate the gate/state via the
    captured main loop's call_soon_threadsafe instead of touching the
    asyncio.Event directly off-loop. Persistence is a plain file write and is
    safe from any thread either way.
    """
    entry = _registry.get(name)

    def _mark_running() -> None:
        entry.gate.set()
        entry.state = "running"

    if entry is not None:
        try:
            asyncio.get_running_loop()
            _mark_running()
        except RuntimeError:
            if _main_loop is not None and not _main_loop.is_closed() and _main_loop.is_running():
                _main_loop.call_soon_threadsafe(_mark_running)
            else:
                # No event loop available at all (e.g. plain sync tests) —
                # mutate directly; nothing else could be racing it.
                _mark_running()
    _persist(name, "running")


def mark_stopped_transient(name: str) -> None:
    """Mark an entry as stopped in memory only — no config persistence.

    Used when an external lifecycle path already owns and manages the real
    task (e.g. /api/pipeline/stop for the voice pipeline) and only needs the
    watchdog view to reflect reality, without writing a 'stopped' override to
    config that would block the task from starting again on next boot.
    """
    entry = _registry.get(name)
    if entry is not None:
        entry.gate.set()  # never leave a future task wedged on a closed gate
        entry.state = "stopped"


def spawn(name: str) -> asyncio.Task | None:
    """Create the task from its factory, honoring persisted state."""
    from core.config import get_config
    _capture_main_loop()
    entry = _get(name)
    persisted = (get_config().watchdog_task_states or {}).get(name)
    if persisted == "stopped":
        entry.state = "stopped"
        return None
    task = asyncio.create_task(entry.factory(), name=name)
    entry.task = task
    if persisted == "paused":
        entry.gate.clear()
        entry.state = "paused"
    return task


def prune_persisted() -> None:
    """Drop persisted states for names no longer registered (renamed/removed tasks)."""
    from core.config import get_config, update_config
    states = dict(get_config().watchdog_task_states or {})
    pruned = {k: v for k, v in states.items() if k in _registry and v in ("paused", "stopped")}
    if pruned != states:
        update_config(watchdog_task_states=pruned)


def _reset_for_tests() -> None:
    global _main_loop
    _registry.clear()
    _pending_reactivations.clear()
    _pending_tasks.clear()
    _main_loop = None
