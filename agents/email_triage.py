from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)

_URGENCY = {"high", "normal", "low"}
_CATEGORY = {"work", "personal", "finance", "newsletter", "notification", "social", "other"}
_SNIPPET = 600
_TIMEOUT = 90


def _to_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1", "y", "spam"}
    return bool(v)


def _fallback(item: dict) -> dict:
    body = str(item.get("body") or "").strip()
    return {
        "urgency": "normal",
        "category": "other",
        "spam": False,
        "summary": (body[:150].replace("\n", " ") or "(no summary)"),
        "draft": "",
    }


def _coerce(raw: dict, item: dict) -> dict:
    if not isinstance(raw, dict):
        return _fallback(item)
    urgency = str(raw.get("urgency", "")).strip().lower()
    if urgency not in _URGENCY:
        urgency = "normal"
    category = str(raw.get("category", "")).strip().lower()
    if category not in _CATEGORY:
        category = "other"
    summary = str(raw.get("summary") or "").strip() or _fallback(item)["summary"]
    draft = str(raw.get("draft") or "").strip()
    if urgency != "high":
        draft = ""
    return {
        "urgency": urgency,
        "category": category,
        "spam": _to_bool(raw.get("spam", False)),
        "summary": summary,
        "draft": draft,
    }


def _extract_array(text: str) -> list:
    """Find the first [...] JSON array in the text and parse it. Raises on failure."""
    start = text.index("[")
    end = text.rindex("]")
    return json.loads(text[start : end + 1])


def triage_messages(items: list[dict]) -> list[dict]:
    """One Ollama /api/chat call classifying every email. Never raises."""
    if not items:
        return []
    from core.config import get_config
    cfg = get_config()

    try:
        numbered = []
        for i, item in enumerate(items, 1):
            from_ = str(item.get("from") or "")
            subject = str(item.get("subject") or "")
            snippet = str(item.get("body") or "").strip()[:_SNIPPET].replace("\n", " ") or "(empty)"
            numbered.append(
                f"{i}. From: {from_}\n"
                f"   Subject: {subject}\n"
                f"   Body: {snippet}"
            )
        prompt = (
            "You are triaging emails. For EACH numbered email, output one JSON object with keys: "
            "urgency (one of: high, normal, low), category (one of: work, personal, finance, "
            "newsletter, notification, social, other), spam (true/false), summary (one sentence), "
            "draft (a suggested reply — ONLY for urgency high, otherwise empty string \"\"). "
            "Reply with ONLY a JSON array of these objects, one per email, in the same order. "
            "No prose.\n\n" + "\n\n".join(numbered)
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
        content = r.json()["message"]["content"]
        arr = _extract_array(content)
    except Exception:
        logger.exception("Email triage classification failed")
        return [_fallback(item) for item in items]

    results = [_coerce(arr[i], items[i]) for i in range(min(len(arr), len(items)))]
    while len(results) < len(items):
        results.append(_fallback(items[len(results)]))
    return results
