from __future__ import annotations
import asyncio
import logging

from core import events
from agents.memory_store import get_memory_store

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 30


async def _check_reminders() -> None:
    store = get_memory_store()
    pending = await asyncio.to_thread(store.get_pending)
    for reminder in pending:
        logger.info("Firing reminder id=%d: %s", reminder["id"], reminder["message"])
        await asyncio.to_thread(store.mark_reminder_done, reminder["id"])
        await events.emit("reminder_fired", {"id": reminder["id"], "message": reminder["message"]})


async def run_reminder_loop() -> None:
    logger.info("Reminder loop started (poll=%ds)", _POLL_INTERVAL_S)
    store = get_memory_store()
    pruned = await asyncio.to_thread(store.prune_done_reminders)
    if pruned:
        logger.info("Pruned %d old done reminders on startup", pruned)
    while True:
        try:
            await _check_reminders()
        except Exception:
            logger.exception("Reminder check failed")
        await asyncio.sleep(_POLL_INTERVAL_S)
