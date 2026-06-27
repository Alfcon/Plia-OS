"""
Background loop that periodically reviews stored facts and recent chat history
to surface actionable patterns as system messages injected via the event bus.
"""
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 3600  # 1 hour between proactive checks
_MAX_FACTS = 30
_MAX_HISTORY = 20


async def run_proactive_memory_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_POLL_INTERVAL)
            await _check()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Proactive memory check failed")


async def _check() -> None:
    from agents.memory_store import get_memory_store
    from agents.chat_history import get_recent
    from agents.llm import call_llm
    from core import events

    store = get_memory_store()

    facts = await asyncio.to_thread(_get_facts, store)
    if not facts:
        return

    history = await asyncio.to_thread(get_recent, _MAX_HISTORY)
    history_text = "\n".join(
        f"{r['role'].upper()}: {r['content']}" for r in history if r.get("content")
    )

    prompt = (
        "You are a proactive assistant. Based on the user's stored facts and recent "
        "conversation, identify ONE actionable insight, pattern, or reminder that would "
        "genuinely help them. Be very specific. If nothing noteworthy, reply NONE.\n\n"
        f"## Stored facts\n{facts}\n\n"
        f"## Recent conversation\n{history_text or '(none)'}"
    )

    try:
        msg = await call_llm([{"role": "user", "content": prompt}])
        insight = (msg.get("content") or "").strip()
    except Exception as exc:
        logger.warning("Proactive memory LLM call failed: %s", exc)
        return

    if insight and insight.upper() != "NONE":
        logger.info("Proactive insight: %s", insight[:120])
        await events.emit("proactive_insight", {"text": insight})


def _get_facts(store) -> str:
    try:
        facts = store.list_all()
        if not facts:
            return ""
        lines = [f"{f['key']}: {f['value']}" for f in facts[:_MAX_FACTS]]
        return "\n".join(lines)
    except Exception:
        return ""
