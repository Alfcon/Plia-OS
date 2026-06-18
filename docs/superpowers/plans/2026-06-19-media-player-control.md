# Media Player Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural-language media player control (play, pause, next, previous, stop, now-playing) via `playerctl` CLI.

**Architecture:** Six synchronous `@tool` functions in `modules/media_tools.py` share a single `_run_playerctl` helper. No new agent, no new LangGraph node — commands route through the existing `respond` node. Media keywords are added to the `"respond"` entry in `_KEYWORD_ROUTES` in `core/supervisor.py`.

**Tech Stack:** Python 3.11+, `subprocess`, `playerctl` CLI (wraps MPRIS2), existing `@tool` decorator from `core/registry.py`.

## Global Constraints

- `playerctl` CLI only — no D-Bus/pydbus dependencies.
- All six tool functions synchronous; no `asyncio` in the module.
- `subprocess.run` with `text=True, capture_output=True, timeout=5` for all calls.
- No new agent, no new LangGraph node, no new entry in `_KNOWN_INTENTS`.
- Media keyword routes go inside the existing `"respond"` list — not a new dict key.
- Module-level `import subprocess` (not local imports inside each function).
- `@tool` decorator from `core/registry.py` — description string is the LLM-visible tool description.

---

### Task 1: Media tools module

**Files:**
- Create: `modules/media_tools.py`
- Test: `tests/test_media_tools.py`

**Interfaces:**
- Consumes: `core.registry.tool` decorator (already exists)
- Produces: `get_now_playing()`, `media_play()`, `media_pause()`, `media_next()`, `media_previous()`, `media_stop()` — all `() -> str`, all auto-discovered by `load_modules()` at startup

- [ ] **Step 1: Write all 10 failing tests**

Create `tests/test_media_tools.py`:

```python
import subprocess
from unittest.mock import patch, MagicMock


def _ok(stdout="", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _err(stderr=""):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


def test_get_now_playing_success():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok("Daft Punk - Get Lucky [spotify]\n")):
        result = get_now_playing()
    assert "Daft Punk" in result
    assert "Get Lucky" in result
    assert "spotify" in result


def test_get_now_playing_empty_metadata():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run", return_value=_ok(" - []\n")):
        result = get_now_playing()
    assert result == "Nothing is playing."


def test_get_now_playing_no_player():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run",
               return_value=_err("No players found\n")):
        result = get_now_playing()
    assert result == "No media player is currently running."


def test_media_play_success():
    from modules.media_tools import media_play
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_play()
    assert result == "Done."
    args = mock_run.call_args[0][0]
    assert args[0] == "playerctl"
    assert "play" in args


def test_media_pause_success():
    from modules.media_tools import media_pause
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_pause()
    assert result == "Done."
    assert "pause" in mock_run.call_args[0][0]


def test_media_next_success():
    from modules.media_tools import media_next
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_next()
    assert result == "Done."
    assert "next" in mock_run.call_args[0][0]


def test_media_previous_success():
    from modules.media_tools import media_previous
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_previous()
    assert result == "Done."
    assert "previous" in mock_run.call_args[0][0]


def test_media_stop_success():
    from modules.media_tools import media_stop
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_stop()
    assert result == "Done."
    assert "stop" in mock_run.call_args[0][0]


def test_playerctl_not_installed():
    from modules.media_tools import media_play
    with patch("modules.media_tools.subprocess.run", side_effect=FileNotFoundError):
        result = media_play()
    assert "playerctl not installed" in result
    assert "apt install playerctl" in result


def test_playerctl_timeout():
    from modules.media_tools import media_play
    exc = subprocess.TimeoutExpired(cmd=["playerctl", "play"], timeout=5)
    with patch("modules.media_tools.subprocess.run", side_effect=exc):
        result = media_play()
    assert result == "Media command timed out."
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
source .venv/bin/activate
pytest tests/test_media_tools.py -v
```

Expected: All 10 FAILED with `ModuleNotFoundError` or `ImportError` (file doesn't exist yet).

- [ ] **Step 3: Create `modules/media_tools.py`**

```python
import subprocess

from core.registry import tool


def _run_playerctl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["playerctl", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            if "No players found" in result.stderr:
                return "No media player is currently running."
            return f"playerctl error: {result.stderr.strip()}"
        return result.stdout.strip() or "Done."
    except FileNotFoundError:
        return "playerctl not installed. Run: sudo apt install playerctl"
    except subprocess.TimeoutExpired:
        return "Media command timed out."


@tool(description="Get the currently playing track, artist, and player name.")
def get_now_playing() -> str:
    result = _run_playerctl(
        "metadata", "--format", "{{artist}} - {{title}} [{{playerName}}]"
    )
    # "Done." = empty stdout (no stdout from playerctl); " - []" = fields unpopulated
    if result == "Done." or result.strip("- []") == "":
        return "Nothing is playing."
    return result


@tool(description="Resume media playback.")
def media_play() -> str:
    return _run_playerctl("play")


@tool(description="Pause media playback.")
def media_pause() -> str:
    return _run_playerctl("pause")


@tool(description="Skip to the next track.")
def media_next() -> str:
    return _run_playerctl("next")


@tool(description="Go back to the previous track.")
def media_previous() -> str:
    return _run_playerctl("previous")


@tool(description="Stop media playback.")
def media_stop() -> str:
    return _run_playerctl("stop")
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
pytest tests/test_media_tools.py -v
```

Expected: All 10 PASSED.

- [ ] **Step 5: Run full suite to check no regressions**

```bash
pytest --tb=short -q
```

Expected: All passing (560+ tests). If failures appear, fix them before committing.

- [ ] **Step 6: Commit**

```bash
git add modules/media_tools.py tests/test_media_tools.py
git commit -m "feat(media): add playerctl-based media player control tools"
```

---

### Task 2: Wire media keyword routes in supervisor

**Files:**
- Modify: `core/supervisor.py` (lines 72–77, the `"respond"` keyword list)

**Interfaces:**
- Consumes: existing `_KEYWORD_ROUTES["respond"]` list (Task 1 must be committed first so `load_modules()` can discover the new tools)
- Produces: nothing new — the `respond` node already exists and handles tool dispatch

**Context:** `_KEYWORD_ROUTES` is a `dict[str, list[str]]` at the top of `core/supervisor.py`. The `"respond"` key currently ends at line 77 with `"lights to "]`. Add media keywords inside that same list. Do NOT add a new dict key — these go inside `"respond"`.

Current state of the `"respond"` entry (lines 72–77):
```python
"respond": ["set a timer", "set timer", "start a timer", "start timer", "timer for",
            "set the volume", "volume up", "volume down", "mute", "unmute",
            "system info", "how much ram", "cpu usage", "disk space",
            "make a note", "don't forget", "add a note", "my notes", "list notes",
            "show notes", "delete note", "clear notes",
            "dim the", "set brightness", "set the brightness", "lights to "],
```

- [ ] **Step 1: Add media keywords to the `"respond"` list**

Change the `"respond"` entry so it reads:

```python
"respond": ["set a timer", "set timer", "start a timer", "start timer", "timer for",
            "set the volume", "volume up", "volume down", "mute", "unmute",
            "system info", "how much ram", "cpu usage", "disk space",
            "make a note", "don't forget", "add a note", "my notes", "list notes",
            "show notes", "delete note", "clear notes",
            "dim the", "set brightness", "set the brightness", "lights to ",
            "play music", "play the music", "resume music", "resume playback",
            "pause music", "pause the music", "pause playback",
            "next track", "skip track", "next song", "skip song",
            "previous track", "go back a track", "previous song", "last song",
            "stop music", "stop the music", "stop playback",
            "what's playing", "what is playing", "now playing",
            "what song", "current song", "current track"],
```

- [ ] **Step 2: Verify keywords present**

```bash
python -c "
from core.supervisor import _KEYWORD_ROUTES
respond = _KEYWORD_ROUTES['respond']
checks = ['play music', 'pause music', 'next track', 'previous track', 'stop music', 'now playing', 'current track']
for kw in checks:
    assert kw in respond, f'MISSING: {kw}'
print('All media keywords present.')
"
```

Expected output: `All media keywords present.`

- [ ] **Step 3: Run full test suite**

```bash
source .venv/bin/activate
pytest --tb=short -q
```

Expected: All passing. No regressions.

- [ ] **Step 4: Commit**

```bash
git add core/supervisor.py
git commit -m "feat(media): add media player keyword routes to respond intent"
```
