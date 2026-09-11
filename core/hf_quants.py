"""Pure helpers for the Hugging Face GGUF quant-listing feature.

No I/O here — `dashboard/server.py` fetches from the HF API and feeds the
results through these functions. See
docs/superpowers/specs/2026-07-30-hf-gguf-pull-design.md.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"^https?://(?:www\.)?huggingface\.co/([\w.-]+)/([\w.-]+)")
_HFCO_RE = re.compile(r"^hf\.co/([\w.-]+)/([\w.-]+)$")
_ID_RE = re.compile(r"^([\w.-]+)/([\w.-]+)$")

# Site sections that appear where a username would (huggingface.co/datasets/…)
_RESERVED = {"datasets", "spaces", "models", "collections", "blog", "docs", "api"}

_SHARD_RE = re.compile(r"-\d{5}-of-\d{5}$", re.IGNORECASE)
_QUANT_RE = re.compile(r"^(i?q\d\w*|f16|bf16|f32)$", re.IGNORECASE)


def parse_hf_repo(text: str | None) -> str | None:
    """Extract "user/repo" from an HF URL, hf.co/ id, or bare id. None if not HF."""
    text = (text or "").strip()
    for rx in (_URL_RE, _HFCO_RE, _ID_RE):
        m = rx.match(text)
        if m:
            user, repo = m.group(1), m.group(2)
            if user.lower() in _RESERVED:
                return None
            return f"{user}/{repo}"
    return None


def _bits(quant: str) -> int:
    m = re.match(r"^i?q(\d)", quant, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 32 if quant.lower() == "f32" else 16


def extract_quants(files: list, vram_gb: float, ram_gb: float) -> list[dict]:
    """Turn an HF tree listing into quant rows with size/bits/fit.

    Sharded GGUFs are collapsed to one row (sizes summed) and marked
    unsupported — Ollama cannot pull split GGUFs. Malformed entries and
    files without a recognizable quant token are skipped.
    """
    found: dict[str, dict] = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        path, size = f.get("path"), f.get("size")
        if not isinstance(path, str) or not path.lower().endswith(".gguf"):
            continue
        if not isinstance(size, (int, float)) or size <= 0:
            continue
        stem = path.rsplit("/", 1)[-1][: -len(".gguf")]
        if stem.lower().startswith(("mmproj", "mm-proj")):
            continue
        sharded = bool(_SHARD_RE.search(stem))
        if sharded:
            stem = _SHARD_RE.sub("", stem)
        token = re.split(r"[.-]", stem)[-1]
        if not _QUANT_RE.match(token):
            continue
        key = token.upper()
        entry = found.get(key)
        if entry is None:
            found[key] = {
                "quant": token, "bytes": size, "unsupported": sharded}
        elif sharded and entry["unsupported"]:
            entry["bytes"] += size
        elif not sharded and entry["unsupported"]:
            # a standalone file supersedes a previously-seen shard set
            found[key] = {"quant": token, "bytes": size, "unsupported": False}
        # duplicate non-shard quant (e.g. a subfolder copy), or a shard
        # arriving after a standalone file of the same quant: keep the first

    rows = []
    for e in found.values():
        size_gb = round(e["bytes"] / 1e9, 1)
        if size_gb * 1.3 <= vram_gb:
            fit = "gpu"
        elif size_gb * 1.2 <= ram_gb:
            fit = "cpu"
        else:
            fit = "none"
        rows.append({
            "quant": e["quant"],
            "size_gb": size_gb,
            "bits": _bits(e["quant"]),
            "fit": fit,
            "unsupported": e["unsupported"],
        })
    rows.sort(key=lambda r: (r["bits"], r["size_gb"]))
    return rows
