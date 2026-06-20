from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_COMPACT_THRESHOLD = 30   # compact when non-system messages exceed this
_KEEP_RECENT = 20         # keep this many most-recent messages verbatim


async def maybe_compact(messages: list[dict]) -> list[dict]:
    """Return compacted message list if over threshold; otherwise return as-is."""
    system = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) <= _COMPACT_THRESHOLD:
        return messages

    to_summarise = non_system[:-_KEEP_RECENT]
    keep = non_system[-_KEEP_RECENT:]

    logger.info("Compacting %d messages into summary", len(to_summarise))
    try:
        summary = await _summarise(to_summarise)
    except Exception:
        logger.exception("Context compaction failed; keeping original messages")
        return messages

    summary_msg = {"role": "system", "content": f"[Earlier conversation summary]\n{summary}"}
    return system + [summary_msg] + keep


async def _summarise(messages: list[dict]) -> str:
    from agents.llm import call_llm
    prompt = (
        "Summarise the following conversation segment concisely. "
        "Preserve key facts, decisions, and anything the user may reference later. "
        "Output plain text, no headers.\n\n"
        + "\n".join(
            f"{m['role'].upper()}: {m.get('content') or ''}"
            for m in messages
            if m.get("content")
        )
    )
    msg = await call_llm([{"role": "user", "content": prompt}])
    return (msg.get("content") or "").strip()
