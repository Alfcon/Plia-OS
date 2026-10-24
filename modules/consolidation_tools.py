from __future__ import annotations

from core.registry import tool


@tool(
    "Run a memory consolidation pass now: synthesize summaries for knowledge-graph entities "
    "whose relationships changed, and report how many graph gaps (sparse entities) remain. "
    "Read-only aside from writing entity summaries."
)
def consolidate_now() -> str:
    try:
        from agents.consolidation import run_consolidation
        stats = run_consolidation()
        return (
            f"Consolidation: summarized {stats['synthesized']} entity(ies), "
            f"{stats['skipped']} skipped, {stats['gaps']} graph gap(s)."
        )
    except Exception as exc:
        return f"Consolidation failed: {exc}"
