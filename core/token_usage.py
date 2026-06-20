from __future__ import annotations
import threading
from dataclasses import dataclass, field

_lock = threading.Lock()


@dataclass
class _Totals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    history: list[dict] = field(default_factory=list)  # last 100 turns


_totals = _Totals()
_HISTORY_CAP = 100


def record(prompt_tokens: int, completion_tokens: int, model: str) -> None:
    with _lock:
        _totals.prompt_tokens += prompt_tokens
        _totals.completion_tokens += completion_tokens
        _totals.calls += 1
        _totals.history.append({
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "model": model,
        })
        if len(_totals.history) > _HISTORY_CAP:
            _totals.history.pop(0)


def get_stats() -> dict:
    with _lock:
        return {
            "calls": _totals.calls,
            "prompt_tokens": _totals.prompt_tokens,
            "completion_tokens": _totals.completion_tokens,
            "total_tokens": _totals.prompt_tokens + _totals.completion_tokens,
            "recent": list(_totals.history[-10:]),
        }


def reset() -> None:
    with _lock:
        _totals.prompt_tokens = 0
        _totals.completion_tokens = 0
        _totals.calls = 0
        _totals.history.clear()
