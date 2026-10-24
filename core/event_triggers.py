from __future__ import annotations
import logging
from core import events

logger = logging.getLogger(__name__)


async def _on_event(payload: dict) -> None:
    from agents.workflow_store import list_workflows, run_workflow
    event_type = payload.get("type")
    for wf in list_workflows():
        if wf.get("event_trigger") == event_type:
            try:
                await run_workflow(wf["name"], payload=payload)
            except Exception:
                logger.exception(
                    "Event trigger failed (workflow=%s, event=%s)",
                    wf["name"],
                    event_type,
                )


def setup_event_triggers() -> None:
    if not events.is_subscribed(_on_event):
        events.subscribe(_on_event)
