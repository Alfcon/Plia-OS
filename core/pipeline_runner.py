import asyncio
import logging
from core import events
from core import pipeline_registry

logger = logging.getLogger(__name__)


async def _on_pipeline_status(payload: dict) -> None:
    if payload.get("type") == "status":
        pipeline_registry.set_state(payload.get("state", "stopped"))


async def start_pipeline() -> None:
    from voice.pipeline import VoicePipeline
    pipeline = VoicePipeline()
    events.subscribe(pipeline._on_event)
    if not events.is_subscribed(_on_pipeline_status):
        events.subscribe(_on_pipeline_status)
    try:
        pipeline.load()
        await pipeline.start()
    except Exception:
        logger.exception(
            "Voice pipeline failed to start. "
            "Dashboard and API remain available."
        )
        await events.emit("status", {"state": "error"})
    finally:
        events.unsubscribe(pipeline._on_event)
        pipeline_registry.set_state("stopped")
        # Only clear the task ref if we are still the registered task — a
        # stop→start race can replace the registry entry before our finally runs.
        if pipeline_registry.get_task() is asyncio.current_task():
            pipeline_registry.set_task(None)
