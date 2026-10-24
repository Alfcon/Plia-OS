from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 60


def synthesize_entity(name: str, type: str, edges: list[dict]) -> str:
    """One Ollama call summarizing an entity from its relationships. Never raises; '' on failure."""
    if not edges:
        return ""
    from core.config import get_config
    cfg = get_config()
    try:
        rel_lines = []
        for e in edges:
            if e.get("direction") == "out":
                rel_lines.append(f"{name} {e['relation']} {e['other']}")
            else:
                rel_lines.append(f"{e['other']} {e['relation']} {name}")
        prompt = (
            f"Summarize what is known about {name} (a {type}) in 1-2 factual sentences, "
            "based ONLY on these relationships. Reply with the summary text only, no preamble.\n\n"
            + "\n".join(rel_lines)
        )
        r = httpx.post(
            f"{cfg.ollama_url}/api/chat",
            json={
                "model": cfg.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=_TIMEOUT,
        )
        return str(r.json()["message"]["content"]).strip()
    except Exception:
        logger.exception("Entity synthesis failed for %s", name)
        return ""


def run_consolidation(min_edges: int = 2) -> dict:
    """Synthesize changed entities + count gaps. Never raises.

    Returns stats {"synthesized","skipped","gaps"}. On an unexpected error the stats
    gathered so far are returned (partial), since any summaries already written are real.
    """
    stats = {"synthesized": 0, "skipped": 0, "gaps": 0}
    try:
        from agents.memory_store import get_memory_store
        store = get_memory_store()
        candidates = store.entities_needing_synthesis(min_edges)
        for c in candidates:
            try:
                g = store.graph_entity(c["name"])
                edges = g["edges"] if g else []
                summary = synthesize_entity(c["name"], c["type"], edges)
                if summary:
                    store.set_entity_summary(c["id"], summary)
                    stats["synthesized"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                logger.exception("Consolidation failed for entity %s", c.get("name"))
                stats["skipped"] += 1
        stats["gaps"] = len(store.sparse_entities(max_edges=1))
    except Exception:
        logger.exception("Consolidation pass failed")
    return stats
