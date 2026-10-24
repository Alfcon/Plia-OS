from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from core import events
from core.watchdog import watchdog_gate

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 60


def _should_fire(
    enabled: bool, scheduled_time: str, now_hhmm: str, last_run_date: str | None, today: str
) -> bool:
    if not enabled:
        return False
    if now_hhmm != scheduled_time:
        return False
    return last_run_date != today


async def run_consolidation_loop() -> None:
    from core.config import get_config
    logger.info("Consolidation loop started (poll=%ds)", _POLL_INTERVAL_S)
    last_run_date: str | None = None
    while True:
        await watchdog_gate("consolidation_loop")
        try:
            cfg = get_config()
            now = datetime.now()
            today = now.date().isoformat()
            if _should_fire(
                bool(getattr(cfg, "consolidation_enabled", False)),
                str(getattr(cfg, "consolidation_time", "03:00")),
                now.strftime("%H:%M"),
                last_run_date,
                today,
            ):
                from agents.consolidation import run_consolidation
                stats = await asyncio.to_thread(run_consolidation)
                last_run_date = today
                logger.info("Consolidation done: %s", stats)
                await events.emit("consolidation_done", stats)
        except Exception:
            logger.exception("Consolidation loop iteration failed")
        await asyncio.sleep(_POLL_INTERVAL_S)
