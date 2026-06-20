from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 60


async def run_cron_loop() -> None:
    from croniter import croniter
    from agents.cron_store import get_cron_store
    from core import events

    logger.info("Cron loop started (poll=%ds)", _POLL_INTERVAL_S)
    store = get_cron_store()
    # Track last-fire time per cron id so we don't double-fire within the same minute
    last_fired: dict[int, str] = {}

    while True:
        await asyncio.sleep(_POLL_INTERVAL_S)
        now = datetime.now(timezone.utc)
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        try:
            jobs = await asyncio.to_thread(store.list_enabled)
            for job in jobs:
                jid = job["id"]
                if last_fired.get(jid) == minute_key:
                    continue
                try:
                    it = croniter(job["expr"], now)
                    prev = it.get_prev(datetime)
                    # Fire if previous occurrence is within this poll window
                    delta = (now - prev).total_seconds()
                    if delta <= _POLL_INTERVAL_S:
                        last_fired[jid] = minute_key
                        logger.info("Cron fired: %s — %s", job["name"], job["message"])
                        await events.emit("reminder_fired", {
                            "id": jid,
                            "message": f"[Cron: {job['name']}] {job['message']}",
                        })
                except Exception:
                    logger.exception("Cron eval error for %r (%s)", job["name"], job["expr"])
        except Exception:
            logger.exception("Cron loop iteration failed")
