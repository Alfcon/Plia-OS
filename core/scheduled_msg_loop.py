from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_scheduled_msg_loop() -> None:
    while True:
        try:
            from core.scheduled_msg_store import get_pending_scheduled, mark_scheduled_done
            from core.config import get_config
            from core.supervisor import run_turn

            pending = await asyncio.to_thread(get_pending_scheduled)
            for msg in pending:
                try:
                    cfg = get_config()
                    messages = [
                        {"role": "system", "content": cfg.system_prompt},
                        {"role": "user", "content": msg["message"]},
                    ]
                    logger.info("Firing scheduled message id=%d: %r", msg["id"], msg["message"])
                    await run_turn(messages)
                except Exception:
                    logger.exception("Scheduled message id=%d failed", msg["id"])
                finally:
                    await asyncio.to_thread(mark_scheduled_done, msg["id"])
        except Exception:
            logger.exception("Scheduled message loop error")
        await asyncio.sleep(30)
