import asyncio
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from core.loader import load_modules
from core.config import get_config
from core.reminder_loop import run_reminder_loop
from core.cron_loop import run_cron_loop
from core.proactive_memory import run_proactive_memory_loop
from core import pipeline_registry
from core.pipeline_runner import start_pipeline
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers
from dashboard.server import router as dashboard_router, setup_event_forwarding

logger = logging.getLogger(__name__)


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
    setup_event_forwarding()
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
        # Start voice pipeline and reminder loop as background tasks
        pipeline_task = asyncio.create_task(start_pipeline())
        pipeline_registry.set_task(pipeline_task)
        reminder_task = asyncio.create_task(run_reminder_loop())
        cron_task = asyncio.create_task(run_cron_loop())
        proactive_task = asyncio.create_task(run_proactive_memory_loop())
        # Start Tor if previously enabled
        tor_task = None
        if get_config().tor_enabled:
            tor_task = asyncio.create_task(_start_tor_if_enabled())
        yield
        pipeline_task.cancel()
        reminder_task.cancel()
        cron_task.cancel()
        proactive_task.cancel()
        if tor_task and not tor_task.done():
            tor_task.cancel()
        for task in filter(None, (pipeline_task, reminder_task, cron_task, proactive_task, tor_task)):
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
