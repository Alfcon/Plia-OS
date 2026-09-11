import asyncio
import pytest

from core import watchdog
from core.config import get_config


async def _noop_loop():
    while True:
        await watchdog.watchdog_gate("worker")
        await asyncio.sleep(0.01)


@pytest.fixture
def worker():
    watchdog.register("worker", _noop_loop, "test worker")
    return "worker"


async def test_register_and_status(worker):
    st = watchdog.status()
    assert st["worker"]["state"] == "running"
    assert st["worker"]["description"] == "test worker"


async def test_gate_unknown_name_returns_immediately():
    await asyncio.wait_for(watchdog.watchdog_gate("nope"), timeout=0.1)


async def test_pause_blocks_gate_and_persists(worker):
    await watchdog.pause("worker")
    assert watchdog.get_entry("worker").state == "paused"
    assert get_config().watchdog_task_states == {"worker": "paused"}
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(watchdog.watchdog_gate("worker"), timeout=0.05)


async def test_resume_opens_gate_and_unpersists(worker):
    await watchdog.pause("worker")
    await watchdog.resume("worker")
    assert watchdog.get_entry("worker").state == "running"
    assert get_config().watchdog_task_states == {}
    await asyncio.wait_for(watchdog.watchdog_gate("worker"), timeout=0.1)


async def test_stop_cancels_task_and_persists(worker):
    task = watchdog.spawn("worker")
    await watchdog.stop("worker")
    assert task.cancelled() or task.done()
    assert watchdog.get_entry("worker").state == "stopped"
    assert get_config().watchdog_task_states == {"worker": "stopped"}


async def test_restart_from_stopped(worker):
    watchdog.spawn("worker")
    await watchdog.stop("worker")
    new = await watchdog.restart("worker")
    assert not new.done()
    assert watchdog.get_entry("worker").state == "running"
    assert get_config().watchdog_task_states == {}
    new.cancel()


async def test_spawn_honors_persisted_stopped():
    from core.config import update_config
    update_config(watchdog_task_states={"worker": "stopped"})
    watchdog.register("worker", _noop_loop, "w")
    assert watchdog.spawn("worker") is None
    assert watchdog.get_entry("worker").state == "stopped"


async def test_spawn_honors_persisted_paused():
    from core.config import update_config
    update_config(watchdog_task_states={"worker": "paused"})
    watchdog.register("worker", _noop_loop, "w")
    task = watchdog.spawn("worker")
    assert task is not None
    assert watchdog.get_entry("worker").state == "paused"
    assert not watchdog.get_entry("worker").gate.is_set()
    task.cancel()


async def test_stop_with_stop_fn(worker):
    called = []

    async def stopper():
        called.append(True)

    watchdog.register("svc", _noop_loop, "svc", stop_fn=stopper)
    await watchdog.stop("svc")
    assert called == [True]


async def test_unknown_name_raises():
    with pytest.raises(KeyError):
        await watchdog.pause("ghost")


async def test_prune_persisted_drops_stale_names(worker):
    from core.config import update_config
    update_config(watchdog_task_states={"worker": "paused", "ghost": "stopped", "bad": "weird"})
    watchdog.prune_persisted()
    assert get_config().watchdog_task_states == {"worker": "paused"}


async def test_stop_fn_called_once_on_stop_then_restart():
    """stop_fn should only be called once even when stop() then restart() are called."""
    called = []

    async def stopper():
        called.append(True)

    watchdog.register("svc", _noop_loop, "svc", stop_fn=stopper)
    task = watchdog.spawn("svc")

    # First stop calls stop_fn
    await watchdog.stop("svc")
    assert called == [True], "stop_fn should be called once on stop()"
    assert watchdog.get_entry("svc").state == "stopped"

    # Restart should not call stop_fn again (already stopped, no live task)
    new_task = await watchdog.restart("svc")
    assert called == [True], "stop_fn should not be called again on restart() from stopped"
    assert watchdog.get_entry("svc").state == "running"
    assert not new_task.done()
    new_task.cancel()


async def test_second_stop_no_op_for_stop_fn():
    """Calling stop() twice on an entry should only call stop_fn once."""
    called = []

    async def stopper():
        called.append(True)

    watchdog.register("svc", _noop_loop, "svc", stop_fn=stopper)
    task = watchdog.spawn("svc")

    # First stop
    await watchdog.stop("svc")
    assert called == [True], "stop_fn called on first stop()"
    assert watchdog.get_entry("svc").state == "stopped"

    # Second stop should not call stop_fn again
    await watchdog.stop("svc")
    assert called == [True], "stop_fn should not be called on second stop()"
    assert watchdog.get_entry("svc").state == "stopped"


import httpx
from httpx import ASGITransport


async def _client():
    from core.main import create_app
    return httpx.AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def test_api_pause_resume_stop_restart(worker):
    watchdog.spawn("worker")
    async with await _client() as client:
        r = await client.post("/api/watchdog/pause/worker")
        assert r.status_code == 200 and r.json()["state"] == "paused"

        r = await client.get("/api/watchdog")
        assert r.json()["named"]["worker"]["state"] == "paused"

        r = await client.post("/api/watchdog/resume/worker")
        assert r.json()["state"] == "running"

        r = await client.post("/api/watchdog/stop/worker")
        assert r.json()["state"] == "stopped"

        r = await client.post("/api/watchdog/restart/worker")
        assert r.json()["state"] == "running"


async def test_api_unknown_name_404(worker):
    async with await _client() as client:
        for verb in ("pause", "resume", "stop", "restart"):
            r = await client.post(f"/api/watchdog/{verb}/ghost")
            assert r.status_code == 404


async def test_paused_reminder_loop_skips_work(monkeypatch):
    """reminder_loop awaits its gate before each check; paused -> no checks."""
    from core import reminder_loop as rl

    calls = []

    async def fake_check():
        calls.append(True)

    monkeypatch.setattr(rl, "_check_reminders", fake_check)
    monkeypatch.setattr(rl, "_POLL_INTERVAL_S", 0.01)

    from unittest.mock import MagicMock
    monkeypatch.setattr(rl, "get_memory_store", MagicMock())

    watchdog.register("reminder_loop", rl.run_reminder_loop, "r")
    task = watchdog.spawn("reminder_loop")
    await asyncio.sleep(0.05)
    assert calls  # ran while running

    await watchdog.pause("reminder_loop")
    await asyncio.sleep(0.02)
    calls.clear()
    await asyncio.sleep(0.05)
    assert calls == []  # paused -> gate blocks -> no work

    await watchdog.resume("reminder_loop")
    await asyncio.sleep(0.05)
    assert calls  # resumed

    task.cancel()


async def test_observer_registered_with_stop_fn(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    import core.main as main_mod

    obs = MagicMock()
    obs.start = AsyncMock()
    obs.stop = AsyncMock()
    obs.is_running = MagicMock(return_value=True)
    monkeypatch.setattr("core.observer.get_observer", lambda: obs)

    main_mod._register_observer_watchdog()
    assert "observer" in watchdog.names()

    await watchdog.stop("observer")
    obs.stop.assert_awaited()
    assert watchdog.get_entry("observer").state == "stopped"


async def test_proactive_registered_with_stop_fn(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    import core.main as main_mod

    pro = MagicMock()
    pro.start = AsyncMock()
    pro.stop = AsyncMock()
    pro.is_running = MagicMock(return_value=True)
    monkeypatch.setattr("core.proactive.get_proactive", lambda: pro)

    main_mod._register_proactive_watchdog()
    assert "proactive" in watchdog.names()

    await watchdog.stop("proactive")
    pro.stop.assert_awaited()
    assert watchdog.get_entry("proactive").state == "stopped"


async def test_observer_loops_share_observer_gate(monkeypatch):
    """Pausing 'observer' blocks its inner loops via the shared gate."""
    watchdog.register("observer", lambda: None, "obs")
    await watchdog.pause("observer")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(watchdog.watchdog_gate("observer"), timeout=0.05)


async def test_proactive_loop_shares_proactive_gate(monkeypatch):
    """Pausing 'proactive' blocks its inner loop via the shared gate."""
    watchdog.register("proactive", lambda: None, "pro")
    await watchdog.pause("proactive")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(watchdog.watchdog_gate("proactive"), timeout=0.05)


async def test_reactivation_warning_running_is_empty(worker):
    watchdog.spawn("worker")
    assert watchdog.reactivation_warning("worker", "x") == ""


async def test_reactivation_warning_paused_warns_and_emits(worker):
    from core import events
    seen = []

    def on_evt(payload):
        if payload.get("type") == "watchdog_reactivate_request":
            seen.append(payload)

    events.subscribe(on_evt)
    try:
        await watchdog.pause("worker")

        warning = watchdog.reactivation_warning("worker", "A reminder was created")
        assert "worker" in warning and "paused" in warning
        await asyncio.sleep(0.05)  # let the fire-and-forget task emit
        assert seen and seen[0]["task"] == "worker" and seen[0]["reason"] == "A reminder was created"
    finally:
        events.unsubscribe(on_evt)


async def test_respond_reactivation_approves(worker):
    watchdog.spawn("worker")
    await watchdog.pause("worker")
    pending_id = await watchdog.request_reactivation("worker", "test")
    name = watchdog.respond_reactivation(pending_id)
    assert name == "worker"
    await watchdog.reactivate(name)
    assert watchdog.get_entry("worker").state == "running"


async def test_respond_reactivation_unknown_id():
    assert watchdog.respond_reactivation("nope") is None


async def test_api_reactivate_respond(worker):
    watchdog.spawn("worker")
    await watchdog.pause("worker")
    pending_id = await watchdog.request_reactivation("worker", "test")
    async with await _client() as client:
        r = await client.post(f"/api/watchdog/reactivate/respond/{pending_id}", json={"approved": True})
        assert r.status_code == 200
    assert watchdog.get_entry("worker").state == "running"


async def test_api_reactivate_respond_unknown_id_404():
    async with await _client() as client:
        r = await client.post("/api/watchdog/reactivate/respond/nope", json={"approved": True})
        assert r.status_code == 404


# ── Finding 1: gate must be re-checked after the sleep, before work ──────────


async def test_paused_proactive_memory_skips_work_during_sleep(monkeypatch):
    """proactive_memory_loop is gate -> sleep -> gate -> _check(). A pause that
    takes effect *during* the sleep must still block the following _check()
    call — one full cycle must not be allowed to complete once paused."""
    from core import proactive_memory as pm

    calls = []

    async def fake_check():
        calls.append(True)

    monkeypatch.setattr(pm, "_check", fake_check)
    monkeypatch.setattr(pm, "_POLL_INTERVAL", 0.05)

    watchdog.register("proactive_memory_loop", pm.run_proactive_memory_loop, "pm")
    task = watchdog.spawn("proactive_memory_loop")
    try:
        await asyncio.sleep(0.02)  # mid-sleep
        await watchdog.pause("proactive_memory_loop")

        # Wait well past the sleep interval — if the gate were only checked
        # at the top of the loop (old bug), _check() would already have run.
        await asyncio.sleep(0.15)
        assert calls == [], "paused mid-sleep must block the following work call"

        await watchdog.resume("proactive_memory_loop")
        await asyncio.sleep(0.1)
        assert calls, "resumed loop should run work again"
    finally:
        task.cancel()


# ── Finding 3: pause/resume state guards + 409 mapping ───────────────────────


async def test_api_resume_on_stopped_409_state_unchanged(worker):
    watchdog.spawn("worker")
    async with await _client() as client:
        r = await client.post("/api/watchdog/stop/worker")
        assert r.json()["state"] == "stopped"

        r = await client.post("/api/watchdog/resume/worker")
        assert r.status_code == 409
    assert watchdog.get_entry("worker").state == "stopped"
    assert get_config().watchdog_task_states == {"worker": "stopped"}


async def test_api_pause_on_stopped_409(worker):
    watchdog.spawn("worker")
    async with await _client() as client:
        r = await client.post("/api/watchdog/stop/worker")
        assert r.json()["state"] == "stopped"

        r = await client.post("/api/watchdog/pause/worker")
        assert r.status_code == 409
    assert watchdog.get_entry("worker").state == "stopped"


async def test_pause_raises_valueerror_directly():
    watchdog.register("worker", _noop_loop, "w")
    watchdog.spawn("worker")
    await watchdog.stop("worker")
    with pytest.raises(ValueError):
        await watchdog.pause("worker")


async def test_resume_raises_valueerror_directly():
    watchdog.register("worker", _noop_loop, "w")
    watchdog.spawn("worker")
    with pytest.raises(ValueError):
        await watchdog.resume("worker")  # already running


# ── Finding 4: clear_state must be thread-safe ───────────────────────────────


async def test_clear_state_thread_safe_from_worker_thread(worker):
    task = watchdog.spawn("worker")
    await watchdog.pause("worker")
    assert not watchdog.get_entry("worker").gate.is_set()

    await asyncio.to_thread(watchdog.clear_state, "worker")

    # Gate should open promptly and any waiter should wake.
    await asyncio.wait_for(watchdog.watchdog_gate("worker"), timeout=1.0)
    assert watchdog.get_entry("worker").state == "running"
    assert get_config().watchdog_task_states == {}
    task.cancel()


# ── Finding 5: pipeline dual-lifecycle sync ──────────────────────────────────


async def test_pipeline_restart_syncs_watchdog(monkeypatch):
    from core import pipeline_registry

    async def fake_start_pipeline():
        await asyncio.sleep(10)

    monkeypatch.setattr("core.pipeline_runner.start_pipeline", fake_start_pipeline)

    watchdog.register("voice_pipeline", lambda: None, "voice")
    await watchdog.pause("voice_pipeline")  # stale watchdog record before restart

    async def _old_pipeline_task():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            pass  # graceful shutdown, like the real pipeline's finally block

    old_task = asyncio.create_task(_old_pipeline_task())
    await asyncio.sleep(0)  # let it actually start sleeping before cancellation
    pipeline_registry.set_task(old_task)
    pipeline_registry.set_state("running")

    async with await _client() as client:
        r = await client.post("/api/pipeline/restart")
        assert r.status_code == 200

    new_task = pipeline_registry.get_task()
    assert new_task is not None and new_task is not old_task
    entry = watchdog.get_entry("voice_pipeline")
    assert entry.task is new_task
    assert entry.state == "running"
    assert get_config().watchdog_task_states == {}

    new_task.cancel()
    try:
        await new_task
    except asyncio.CancelledError:
        pass


async def test_pipeline_stop_marks_watchdog_transient_without_persisting():
    from core import pipeline_registry

    watchdog.register("voice_pipeline", lambda: None, "voice")
    dummy_task = asyncio.create_task(asyncio.sleep(100))
    pipeline_registry.set_task(dummy_task)
    pipeline_registry.set_state("running")

    async with await _client() as client:
        r = await client.post("/api/pipeline/stop")
        assert r.status_code == 200

    assert watchdog.get_entry("voice_pipeline").state == "stopped"
    # Transient only — a persisted override here would block the real
    # voice_pipeline watchdog task from spawning again at next boot.
    assert get_config().watchdog_task_states == {}


# ── Finding 2: paused observer must discard keystrokes, not buffer them ─────


async def test_observer_key_loop_discards_events_while_paused(monkeypatch):
    """Regression: _key_loop used to await the gate *after* reading an evdev
    event, so events queued at the OS level while paused would all get
    processed in a burst once resumed. Fixed by checking is_paused() right
    after the read and dropping (continue) instead of blocking on the gate.
    """
    import sys
    import types
    import core.observer as obs_mod

    queue: asyncio.Queue = asyncio.Queue()

    class _FakeEcodes:
        EV_KEY = 1
        KEY_LEFTSHIFT = 42
        KEY_RIGHTSHIFT = 54

    class _FakeKeyEvent:
        key_down = 1
        key_up = 0

    class _FakeEvent:
        def __init__(self, code, keystate):
            self.type = _FakeEcodes.EV_KEY
            self.scancode = code
            self.keystate = keystate

    class _FakeDevice:
        async def async_read_loop(self):
            while True:
                ev = await queue.get()
                if ev is None:
                    return
                yield ev

    fake_evdev = types.ModuleType("evdev")
    fake_evdev.ecodes = _FakeEcodes
    fake_evdev.KeyEvent = _FakeKeyEvent
    fake_evdev.categorize = lambda e: e
    fake_evdev.InputDevice = lambda path: _FakeDevice()

    monkeypatch.setitem(sys.modules, "evdev", fake_evdev)
    monkeypatch.setattr(obs_mod, "_find_keyboard", lambda: "/fake/dev0")

    processed = []
    monkeypatch.setattr(
        obs_mod, "_keycode_to_char",
        lambda code, shift: processed.append(code) or "x",
    )

    watchdog.register("observer", lambda: None, "obs")
    obs = obs_mod.ObserverService()
    task = asyncio.create_task(obs._key_loop())
    try:
        await asyncio.sleep(0.02)  # let the loop reach the queue.get() await

        await watchdog.pause("observer")
        for code in (30, 48, 46):  # arbitrary scancodes
            await queue.put(_FakeEvent(code, _FakeKeyEvent.key_down))
        await asyncio.sleep(0.05)
        assert processed == [], "keystrokes read while paused must be discarded"

        await watchdog.resume("observer")
        await queue.put(_FakeEvent(31, _FakeKeyEvent.key_down))
        await asyncio.sleep(0.05)
        assert processed == [31], "keystrokes read while running must be processed"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_reactivation_warning_thread_safe_via_real_tool_dispatch():
    """Regression: sync @tool functions are dispatched through
    core.registry.call_tool_async, which runs them in a worker thread via
    asyncio.to_thread — so reactivation_warning must NOT rely on
    asyncio.get_running_loop() succeeding in that thread. Exercises the real
    dispatch path (not a direct function call) for set_reminder."""
    from core import events, registry
    from modules.reminder_tools import set_reminder

    registry.register_tool(
        name="set_reminder",
        fn=set_reminder,
        description="test",
        parameters={"type": "object", "properties": {}},
    )

    watchdog.register("reminder_loop", _noop_loop, "reminders")
    watchdog.spawn("reminder_loop")
    await watchdog.pause("reminder_loop")

    seen = []

    def on_evt(payload):
        if payload.get("type") == "watchdog_reactivate_request":
            seen.append(payload)

    events.subscribe(on_evt)
    try:
        result = await registry.call_tool_async(
            "set_reminder", {"message": "take meds", "minutes": 5}
        )
    finally:
        events.unsubscribe(on_evt)

    assert "reminder_loop" in result and "dashboard prompt" in result
    await asyncio.sleep(0.05)  # let the fire-and-forget task/threadsafe call land
    assert seen and seen[0]["task"] == "reminder_loop"
    assert seen[0]["reason"] == "A reminder was created"
