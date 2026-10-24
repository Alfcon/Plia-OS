from __future__ import annotations

from core.registry import tool


@tool(
    "Recommend local LLM models that fit THIS machine's GPU VRAM and RAM. Scans hardware and "
    "ranks a curated catalog into GPU-fast / CPU-capable / too-big tiers. Optional 'want' "
    "filters by use: general, tools, coding, vision, tiny, reasoning. Read-only — suggests "
    "only; pulling or switching happens via the dashboard or on explicit user request."
)
def recommend_models(want: str = "") -> str:
    try:
        from core.model_catalog import current_hardware, rank_catalog
        from core.config import get_config

        vram, ram = current_hardware()
        ranked = rank_catalog(vram, ram)
        want = (want or "").strip().lower()
        if want:
            ranked = [r for r in ranked if want in r["tags"]]
        if not ranked:
            return f"No catalog models match '{want}'."

        current = getattr(get_config(), "ollama_model", "") or ""
        gpu = [r for r in ranked if r["tier"] == "gpu"][:5]
        cpu = [r for r in ranked if r["tier"] == "cpu"][:3]

        def fmt(r):
            mark = "  ← active" if r["name"] == current else ""
            return f"  {r['label']} ({r['name']}) — {r['size_gb']:.1f} GB{mark}"

        lines = [f"Hardware: {vram:.1f} GB VRAM, {ram:.1f} GB RAM."]
        if gpu:
            lines.append("GPU-fast (fits VRAM):")
            lines += [fmt(r) for r in gpu]
        if cpu:
            lines.append("CPU-capable (RAM only, slower):")
            lines += [fmt(r) for r in cpu]
        if not gpu and not cpu:
            lines.append("No catalog model fits this machine's VRAM or RAM.")
        return "\n".join(lines)
    except Exception as exc:
        return f"Couldn't build model recommendations: {exc}"
