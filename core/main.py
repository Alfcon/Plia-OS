import asyncio
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from core.log_buffer import install as _install_log_buffer
_install_log_buffer()
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from core.loader import load_modules
from core.config import get_config
from core.reminder_loop import run_reminder_loop
from core.cron_loop import run_cron_loop
from core.proactive_memory import run_proactive_memory_loop
from core.scheduled_msg_loop import run_scheduled_msg_loop
from core.consolidation_loop import run_consolidation_loop
from core import pipeline_registry
from core.pipeline_runner import start_pipeline
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers
from dashboard.server import (
    router as dashboard_router,
    setup_event_forwarding,
    run_vram_sampler,
    run_mcp_health_monitor,
    run_resource_alert_loop,
)

logger = logging.getLogger(__name__)


async def _run_pipeline() -> None:
    # Keep pipeline_registry pointing at the live task even after a
    # watchdog restart replaces the one created at startup.
    pipeline_registry.set_task(asyncio.current_task())
    await start_pipeline()


_CORE_LOOPS = [
    ("voice_pipeline", _run_pipeline,
     "Voice state machine: wake word → listen → STT → LLM turn → TTS playback."),
    ("reminder_loop", run_reminder_loop,
     "Polls reminders every 30 s, fires overdue ones as spoken announcements."),
    ("cron_loop", run_cron_loop,
     "Runs user-defined cron schedules, firing each job at its due minute."),
    ("proactive_memory_loop", run_proactive_memory_loop,
     "Reviews stored facts and recent chat to surface actionable patterns."),
    ("scheduled_msg_loop", run_scheduled_msg_loop,
     "Delivers scheduled messages at their due time via a supervisor turn."),
    ("consolidation_loop", run_consolidation_loop,
     "Daily chat-history consolidation into long-term memory."),
    ("vram_sampler", run_vram_sampler,
     "Samples GPU VRAM usage for the dashboard stats bar."),
    ("mcp_health_monitor", run_mcp_health_monitor,
     "Health-checks connected MCP servers and flags dead ones."),
    ("resource_alert_loop", run_resource_alert_loop,
     "Watches CPU/RAM/disk/GPU against thresholds and emits alerts."),
]


def _spawn_watched(name: str, factory, description: str):
    from core import watchdog
    watchdog.register(name, factory, description)
    return watchdog.spawn(name)  # honors persisted paused/stopped; may be None


async def _start_observer() -> None:
    try:
        import core.observer as obs_mod
        await obs_mod.get_observer().start()
    except Exception as exc:
        from core.config import update_config
        await asyncio.to_thread(update_config, observer_enabled=False)
        logger.warning("Observer startup failed, disabled: %s", exc)


async def _start_proactive() -> None:
    try:
        import core.proactive as pro_mod
        await pro_mod.get_proactive().start()
    except Exception as exc:
        from core.config import update_config
        await asyncio.to_thread(update_config, proactive_enabled=False)
        logger.warning("Proactive assistant startup failed, disabled: %s", exc)


def _register_observer_watchdog() -> None:
    from core import watchdog
    import core.observer as obs_mod

    async def _stop_observer() -> None:
        await obs_mod.get_observer().stop()

    watchdog.register(
        "observer", _start_observer,
        "User activity observer: screen, focus, and key capture loops.",
        stop_fn=_stop_observer,
        is_running_fn=lambda: obs_mod.get_observer().is_running(),
    )


def _register_proactive_watchdog() -> None:
    from core import watchdog
    import core.proactive as pro_mod

    async def _stop_proactive() -> None:
        await pro_mod.get_proactive().stop()

    watchdog.register(
        "proactive", _start_proactive,
        "Proactive assistant: watches activity and offers unprompted help.",
        stop_fn=_stop_proactive,
        is_running_fn=lambda: pro_mod.get_proactive().is_running(),
    )


async def _start_tor_if_enabled() -> None:
    import core.tor_manager as tm
    result = await asyncio.to_thread(tm.enable)
    if result.lower().startswith("tor enabled"):
        await tm._start_monitor(tm._last_tor_uid)
    else:
        from core.config import update_config
        await asyncio.to_thread(update_config, tor_enabled=False)
        logger.warning("Tor startup failed: %s", result)


def create_app() -> FastAPI:
    # Load modules and wire event bus eagerly so they are available
    # before the first request regardless of whether the ASGI lifespan
    # fires (e.g. during testing with httpx ASGITransport).
    load_modules()
    from agents.ollama_vram import register_ollama
    register_ollama()
    setup_event_forwarding()
    from core.event_triggers import setup_event_triggers
    setup_event_triggers()
    from core.notifier import setup_notifier
    setup_notifier()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            import psutil
            psutil.cpu_percent()  # prime baseline; first call always returns 0.0 otherwise
        except ImportError:
            pass
        await load_mcp_servers()
        # Start background loops as named, watchdog-registered tasks
        for loop_name, factory, description in _CORE_LOOPS:
            _spawn_watched(loop_name, factory, description)
        # Start Tor if previously enabled
        tor_task = None
        if get_config().tor_enabled:
            tor_task = asyncio.create_task(_start_tor_if_enabled(), name="tor_startup")
        # Register Observer and Proactive unconditionally so both always
        # appear in the watchdog panel; only spawn their tasks if enabled.
        from core import watchdog
        _register_observer_watchdog()
        _register_proactive_watchdog()
        if get_config().observer_enabled:
            watchdog.spawn("observer")  # None if persisted stopped
        if get_config().proactive_enabled:
            watchdog.spawn("proactive")
        # All registrations done — drop persisted states for tasks that no longer exist
        await asyncio.to_thread(watchdog.prune_persisted)
        yield
        # Cancel via the watchdog registry so tasks replaced by a restart
        # are cancelled instead of the stale startup references.
        from core import watchdog as _wd
        to_await = []
        for loop_name, _, _ in _CORE_LOOPS:
            entry = _wd.get_entry(loop_name)
            task = entry.task if entry else None
            if task and not task.done():
                task.cancel()
                to_await.append(task)
        for loop_name in ("observer", "proactive"):
            entry = _wd.get_entry(loop_name)
            task = entry.task if entry else None
            if task and not task.done():
                task.cancel()
                to_await.append(task)
        if tor_task and not tor_task.done():
            tor_task.cancel()
            to_await.append(tor_task)
        for task in to_await:
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Clean up Tor system state (iptables, monitor task, daemon) without
        # touching tor_enabled config so it restarts on next boot.
        import core.tor_manager as tm
        if tm._monitor_task and not tm._monitor_task.done():
            tm._monitor_task.cancel()
            try:
                await tm._monitor_task
            except asyncio.CancelledError:
                pass
        if tm._exit_ip is not None:
            await asyncio.to_thread(tm._system_cleanup)
        await shutdown_mcp_servers()

    app = FastAPI(title="Plia-OS", lifespan=lifespan)
    app.include_router(dashboard_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent.parent / "dashboard" / "static"),
        name="static",
    )
    from dashboard.server import UPLOADS_DIR
    app.mount(
        "/uploads",
        StaticFiles(directory=UPLOADS_DIR),
        name="uploads",
    )
    return app


if __name__ == "__main__":
    import uvicorn
    cfg = get_config()
    uvicorn.run("core.main:create_app", factory=True, host=cfg.host, port=cfg.port, reload=False)
