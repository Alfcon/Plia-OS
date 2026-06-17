# Voice Context Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reload recent chat history into the voice pipeline's in-memory conversation on startup so the assistant retains context across restarts.

**Architecture:** `voice/pipeline.py` `load()` calls `agents.chat_history.get_recent()` after initialising the services and rebuilds `self._conversation` from the returned rows — system prompt first, then the last `_HISTORY_PRELOAD` (20) non-system messages. The existing `clear_history` event handler continues to reset conversation to system-only (user explicitly cleared; don't reload).

**Tech Stack:** Python stdlib, existing `agents.chat_history` SQLite module, `voice/pipeline.py`.

---

## File Structure

```
voice/pipeline.py                        MOD — load() preloads history, _HISTORY_PRELOAD constant
tests/test_pipeline_history_preload.py   NEW — 4 unit tests for history preload behaviour
```

---

### Task 1: Preload chat history on pipeline load

**Files:**
- Modify: `voice/pipeline.py:39-47` (the `load()` method)
- Create: `tests/test_pipeline_history_preload.py`

**Context you need:**

`agents/chat_history.py` exports `get_recent(n: int = 100) -> list[dict]`.
Each dict has keys `role`, `content`, `ts`. `ts` is not needed by the LLM — strip it.

`voice/pipeline.py` current `load()` (lines 39-47):
```python
def load(self) -> None:
    self._wake.load()
    self._stt.load()
    self._tts.load()
    config = get_config()
    self._conversation = [{"role": "system", "content": config.system_prompt}]
    if self._on_event not in events._subscribers:
        events.subscribe(self._on_event)
```

Existing test pattern (from `tests/test_pipeline.py`) for mocking services:
```python
pipeline = VoicePipeline()
pipeline._wake = MagicMock()
pipeline._stt = MagicMock()
pipeline._tts = MagicMock()
```

Patch `agents.chat_history.get_recent` (not `voice.pipeline.get_recent`) because `load()` uses a lazy import inside the function body.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_history_preload.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from voice.pipeline import VoicePipeline


def _pipeline():
    p = VoicePipeline()
    p._wake = MagicMock()
    p._stt = MagicMock()
    p._tts = MagicMock()
    return p


def test_load_restores_recent_history():
    history = [
        {"role": "user",      "content": "Hello",       "ts": "2026-01-01T00:00:00+00:00"},
        {"role": "assistant", "content": "Hi there!",   "ts": "2026-01-01T00:00:01+00:00"},
    ]
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=history):
        p.load()
    assert p._conversation[0]["role"] == "system"
    assert p._conversation[1] == {"role": "user",      "content": "Hello"}
    assert p._conversation[2] == {"role": "assistant", "content": "Hi there!"}
    assert len(p._conversation) == 3


def test_load_empty_history():
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=[]):
        p.load()
    assert len(p._conversation) == 1
    assert p._conversation[0]["role"] == "system"


def test_load_skips_system_messages_in_history():
    history = [
        {"role": "system",    "content": "Old prompt",  "ts": "2026-01-01T00:00:00+00:00"},
        {"role": "user",      "content": "Remember me", "ts": "2026-01-01T00:00:01+00:00"},
    ]
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=history):
        p.load()
    roles = [m["role"] for m in p._conversation]
    assert roles.count("system") == 1
    assert roles == ["system", "user"]


def test_load_calls_get_recent_with_preload_limit():
    from voice.pipeline import _HISTORY_PRELOAD
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=[]) as mock_get:
        p.load()
    mock_get.assert_called_once_with(_HISTORY_PRELOAD)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/test_pipeline_history_preload.py -v 2>&1 | head -15
```

Expected: `ImportError: cannot import name '_HISTORY_PRELOAD' from 'voice.pipeline'` (or AttributeError on `p._conversation` shape mismatch).

- [ ] **Step 3: Modify voice/pipeline.py**

Add module-level constant after the existing constants (around line 20):

```python
_HISTORY_PRELOAD = 20
```

Replace the `load()` method (lines 39–47) with:

```python
def load(self) -> None:
    self._wake.load()
    self._stt.load()
    self._tts.load()
    config = get_config()
    from agents.chat_history import get_recent
    history = get_recent(_HISTORY_PRELOAD)
    self._conversation = [{"role": "system", "content": config.system_prompt}] + [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m["role"] != "system"
    ]
    if self._on_event not in events._subscribers:
        events.subscribe(self._on_event)
```

- [ ] **Step 4: Run new tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_pipeline_history_preload.py -v
```

Expected: 4 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥187)

- [ ] **Step 6: Commit**

```bash
git add voice/pipeline.py tests/test_pipeline_history_preload.py
git commit -m "feat(pipeline): preload recent chat history on startup for context persistence"
```
