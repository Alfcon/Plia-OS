from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from core import events

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 60


async def _fire_cron_job(job: dict) -> None:
    msg = job["message"]
    if msg.startswith("tool:"):
        tool_name = msg[5:].strip()
        try:
            from core.registry import call_tool_async
            msg = str(await call_tool_async(tool_name, {}))
        except Exception:
            logger.exception("Cron tool call %r failed", tool_name)
            msg = f"Failed to run {tool_name}."
    elif msg.startswith("workflow:"):
        wf_name = msg[9:].strip()
        try:
            from agents.workflow_store import run_workflow
            results = await run_workflow(wf_name)
            last = next((r["result"] for r in reversed(results) if r.get("result")), "")
            msg = f"Workflow '{wf_name}' complete. {last}".strip()
        except Exception:
            logger.exception("Cron workflow %r failed", wf_name)
            msg = f"Workflow '{wf_name}' failed."
    await events.emit("reminder_fired", {
        "id": job["id"],
        "message": f"[Cron: {job['name']}] {msg}",
    })


async def run_cron_loop() -> None:
    from croniter import croniter
    from agents.cron_store import get_cron_store

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
                        await _fire_cron_job(job)
                except Exception:
                    logger.exception("Cron eval error for %r (%s)", job["name"], job["expr"])
        except Exception:
            logger.exception("Cron loop iteration failed")
