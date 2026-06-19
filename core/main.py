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
from core import pipeline_registry
from core.pipeline_runner import start_pipeline
from core.mcp_client import load_mcp_servers, shutdown_mcp_servers
from dashboard.server import router as dashboard_router, setup_event_forwarding

logger = logging.getLogger(__name__)


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
        yield
        pipeline_task.cancel()
        reminder_task.cancel()
        for task in (pipeline_task, reminder_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
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
