from __future__ import annotations
import asyncio
import logging
import subprocess

from core import events
from core.config import get_config

logger = logging.getLogger(__name__)


async def _on_reminder_fired(payload: dict) -> None:
    if payload.get("type") != "reminder_fired":
        return
    if not get_config().desktop_notifications:
        return
    message = payload.get("message", "")
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["notify-send", "Plia Reminder", message],
            timeout=5,
            capture_output=True,
        )
    except FileNotFoundError:
        logger.warning("notify-send not available — desktop notifications disabled")
    except Exception:
        logger.exception("Failed to send desktop notification")


def setup_notifier() -> None:
    events.subscribe(_on_reminder_fired)
