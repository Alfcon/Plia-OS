"""Curated catalog of local LLM models + pure hardware-fit ranking.

Offline and deterministic: rank_catalog is a pure function of (vram_gb, ram_gb).
Hardware is read only in current_hardware(). llmfit is intentionally NOT used here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.system_fit import get_gpu_vram_gb

logger = logging.getLogger(__name__)

_RAM_FACTOR = 1.2  # CPU inference needs ~model size + working set in RAM
_TIER_ORDER = {"gpu": 0, "cpu": 1, "none": 2}


@dataclass(frozen=True)
class CatalogModel:
    name: str          # exact Ollama tag, e.g. "llama3.1:8b"
    label: str         # human name, e.g. "Llama 3.1 8B"
    params_b: float    # billions of parameters
    size_gb: float     # download/disk size at default quant
    vram_gb: float     # approx VRAM to run on GPU at default quant
    tags: tuple[str, ...]


# Approximate figures at Ollama default quant (Q4_K_M-ish). Hand-maintained.
CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel("qwen2.5:0.5b", "Qwen2.5 0.5B", 0.5, 0.4, 0.8, ("tiny", "general")),
    CatalogModel("llama3.2:1b", "Llama 3.2 1B", 1, 1.3, 1.8, ("tiny", "general")),
    CatalogModel("qwen2.5:1.5b", "Qwen2.5 1.5B", 1.5, 1.0, 1.6, ("tiny", "general", "tools")),
    CatalogModel("llama3.2:3b", "Llama 3.2 3B", 3, 2.0, 3.2, ("general", "tools")),
    CatalogModel("phi3.5:3.8b", "Phi-3.5 3.8B", 3.8, 2.2, 3.5, ("general", "reasoning")),
    CatalogModel("qwen2.5:7b", "Qwen2.5 7B", 7, 4.7, 6.0, ("general", "tools")),
    CatalogModel("llama3.1:8b", "Llama 3.1 8B", 8, 4.9, 6.5, ("general", "tools")),
    CatalogModel("mistral:7b", "Mistral 7B", 7, 4.1, 5.5, ("general",)),
    CatalogModel("qwen2.5-coder:7b", "Qwen2.5 Coder 7B", 7, 4.7, 6.0, ("coding", "tools")),
    CatalogModel("llava:7b", "LLaVA 7B", 7, 4.7, 6.5, ("vision",)),
    CatalogModel("gemma2:9b", "Gemma 2 9B", 9, 5.4, 7.5, ("general",)),
    CatalogModel("qwen2.5:14b", "Qwen2.5 14B", 14, 9.0, 11.0, ("general", "tools", "reasoning")),
    CatalogModel("qwen2.5-coder:14b", "Qwen2.5 Coder 14B", 14, 9.0, 11.0, ("coding", "tools")),
    CatalogModel("gemma2:27b", "Gemma 2 27B", 27, 16.0, 20.0, ("general",)),
    CatalogModel("qwen2.5:32b", "Qwen2.5 32B", 32, 20.0, 24.0, ("general", "reasoning")),
    CatalogModel("qwen2.5-coder:32b", "Qwen2.5 Coder 32B", 32, 20.0, 24.0, ("coding", "tools")),
    CatalogModel("llama3.3:70b", "Llama 3.3 70B", 70, 43.0, 48.0, ("general", "tools", "reasoning")),
    CatalogModel("qwen2.5:72b", "Qwen2.5 72B", 72, 47.0, 52.0, ("general", "reasoning")),
)


def rank_catalog(
    vram_gb: float, ram_gb: float, catalog: tuple[CatalogModel, ...] = CATALOG
) -> list[dict]:
    """Rank every catalog model into a fit tier for this hardware. Pure function."""
    rows: list[dict] = []
    for m in catalog:
        if vram_gb >= m.vram_gb:
            tier = "gpu"
            reason = f"Fits GPU ({m.vram_gb:.1f} GB VRAM ≤ {vram_gb:.1f} GB)"
        elif ram_gb >= m.size_gb * _RAM_FACTOR:
            tier = "cpu"
            reason = f"Runs on CPU/RAM (~{m.size_gb:.1f} GB), slower — exceeds {vram_gb:.1f} GB VRAM"
        else:
            tier = "none"
            reason = f"Too big: needs {m.vram_gb:.1f} GB VRAM or ~{m.size_gb:.1f} GB RAM"
        rows.append({
            "name": m.name,
            "label": m.label,
            "params_b": m.params_b,
            "size_gb": m.size_gb,
            "vram_gb": m.vram_gb,
            "tags": list(m.tags),
            "tier": tier,
            "reason": reason,
        })
    rows.sort(key=lambda r: (_TIER_ORDER[r["tier"]], -r["params_b"]))
    return rows


_INSTALLED_VRAM_FACTOR = 1.3  # download size → VRAM estimate; curated ratios are 1.28–1.39


def merge_installed(
    rows: list[dict], installed: list[dict], vram_gb: float, ram_gb: float
) -> list[dict]:
    """Merge locally installed Ollama models into ranked rows. No I/O; mutates and returns `rows` in place.

    Exact-name matches mark the curated row installed; unknown models are
    appended with VRAM estimated from download size. Malformed entries skipped.
    """
    known = {r["name"]: r for r in rows}
    for r in rows:
        r["installed"] = False
    for m in installed:
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        if not isinstance(name, str) or not name:
            continue
        row = known.get(name)
        if row is not None:
            row["installed"] = True
            if "installed" not in row["tags"]:
                row["tags"].append("installed")
            continue
        size = m.get("size")
        if not isinstance(size, (int, float)) or size <= 0:
            continue
        size_gb = round(size / 1e9, 1)
        est_vram = round(size_gb * _INSTALLED_VRAM_FACTOR, 1)
        if vram_gb >= est_vram:
            tier = "gpu"
            reason = f"Installed; fits GPU (~{est_vram:.1f} GB VRAM ≤ {vram_gb:.1f} GB)"
        elif ram_gb >= size_gb * _RAM_FACTOR:
            tier = "cpu"
            reason = f"Installed; runs on CPU/RAM (~{size_gb:.1f} GB), slower — exceeds {vram_gb:.1f} GB VRAM"
        else:
            tier = "none"
            reason = f"Installed; needs ~{est_vram:.1f} GB VRAM or ~{size_gb:.1f} GB RAM"
        new_row = {
            "name": name,
            "label": name,
            "params_b": 0,
            "size_gb": size_gb,
            "vram_gb": est_vram,
            "tags": ["installed"],
            "tier": tier,
            "reason": reason,
            "installed": True,
        }
        rows.append(new_row)
        known[name] = new_row
    rows.sort(key=lambda r: (_TIER_ORDER[r["tier"]], -r["params_b"], -r["size_gb"]))
    return rows


def current_hardware() -> tuple[float, float]:
    """Return (vram_gb, ram_gb) for this machine. Never raises."""
    vram = get_gpu_vram_gb()
    try:
        import psutil
        ram = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        logger.debug("RAM detection failed", exc_info=True)
        ram = 0.0
    return vram, ram
