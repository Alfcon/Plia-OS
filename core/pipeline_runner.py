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
    from core.config import get_config
    config = get_config()
    pipeline = VoicePipeline()
    events.subscribe(pipeline._on_event)
    if _on_pipeline_status not in events._subscribers:
        events.subscribe(_on_pipeline_status)
    try:
        pipeline.load()
        await pipeline.start()
    except Exception:
        logger.exception(
            "Voice pipeline failed to start. "
            "Dashboard and API remain available."
        )
    finally:
        pipeline_registry.set_state("stopped")
