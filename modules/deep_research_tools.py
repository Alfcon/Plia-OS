from __future__ import annotations

from typing import Literal

from core.registry import tool


@tool(
    "Research a topic in depth: plan sub-queries, search and read sources, and write a "
    "cited Markdown report with a 'what's still unknown' section. "
    "source: web | academic | both (default web). max_subqueries: how many angles (default 4). "
    "output_formats: comma list of chat, file, browser (default chat)."
)
async def deep_research(topic: str, source: Literal["web", "academic", "both"] = "web", max_subqueries: int = 4,
                        output_formats: str = "chat") -> str:
    from agents.deep_research import run_deep_research
    return await run_deep_research(topic, source, max_subqueries, output_formats)
