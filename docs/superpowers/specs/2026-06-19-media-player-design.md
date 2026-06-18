# Media Player Control Design

## Goal

Add natural-language media player control to Plia-OS: play, pause, next, previous, stop, and now-playing queries. Works with any MPRIS2-compatible player (Spotify, VLC, browsers, mpv, etc.) via `playerctl`.

## Architecture

No new agent. Six `@tool` functions in `modules/media_tools.py` use `playerctl` CLI. The existing `respond` node in the supervisor already handles direct tool dispatch — media commands are single-action operations with no intent ambiguity requiring a dedicated agent. Keyword routes added to the `"respond"` entry in `_KEYWORD_ROUTES`.

## Components

### `modules/media_tools.py` (new, ~80 lines)

Six synchronous `@tool` functions. All use `subprocess.run` with `timeout=5`. All return plain strings.

```python
import subprocess
from core.registry import tool

def _run_playerctl(*args: str) -> str:
    """Run a playerctl command. Returns stdout on success or an error string."""
```

`_run_playerctl` is the single shared helper:
- Runs `["playerctl", *args]` with `capture_output=True, text=True, timeout=5`
- `FileNotFoundError` → `"playerctl not installed. Run: sudo apt install playerctl"`
- `subprocess.TimeoutExpired` → `"Media command timed out."`
- Non-zero returncode and "No players found" in stderr → `"No media player is currently running."`
- Non-zero returncode (other) → `"playerctl error: {stderr.strip()}"`
- Zero returncode → `stdout.strip() or "Done."`

| Tool | `playerctl` args | Description registered with `@tool` |
|---|---|---|
| `get_now_playing()` | `metadata --format "{{artist}} - {{title}} [{{playerName}}]"` | Get the currently playing track, artist, and player name |
| `media_play()` | `play` | Resume media playback |
| `media_pause()` | `pause` | Pause media playback |
| `media_next()` | `next` | Skip to the next track |
| `media_previous()` | `previous` | Go back to the previous track |
| `media_stop()` | `stop` | Stop media playback |

`get_now_playing`: if `playerctl` exits zero but stdout is empty or `" - "` only (no metadata), return `"Nothing is playing."`.

### `core/supervisor.py`

Extend the `"respond"` entry in `_KEYWORD_ROUTES` with media keywords. These go after the existing volume/mute/timer/notes entries:

```python
"play music", "play the music", "resume music", "resume playback",
"pause music", "pause the music", "pause playback",
"next track", "skip track", "next song", "skip song",
"previous track", "go back a track", "previous song", "last song",
"stop music", "stop the music", "stop playback",
"what's playing", "what is playing", "now playing",
"what song", "current song", "current track",
```

No new intent, no new graph node. The `respond` node's LLM sees the six media tool schemas alongside all other tools and calls the right one.

## Data Flow

```
user: "next track"
  → _keyword_route matches "next track" → intent = "respond"
  → _respond_node: LLM sees media_next tool schema → emits tool_call
  → call_tool("media_next", {}) → subprocess.run(["playerctl", "next"])
  → returns "Done." → LLM synthesises response → TTS
```

```
user: "what's playing?"
  → _keyword_route matches "what's playing" → intent = "respond"
  → LLM calls get_now_playing() → "Daft Punk - Get Lucky [spotify]"
  → LLM says "Now playing: Get Lucky by Daft Punk on Spotify" → TTS
```

## Error Handling

| Condition | Return value |
|---|---|
| `playerctl` not installed | `"playerctl not installed. Run: sudo apt install playerctl"` |
| No active player | `"No media player is currently running."` |
| Subprocess timeout | `"Media command timed out."` |
| Other non-zero exit | `"playerctl error: {stderr}"` |
| Play/pause/next/stop succeeds with no stdout | `"Done."` |
| `get_now_playing` returns empty metadata | `"Nothing is playing."` |

## Tests

### `tests/test_media_tools.py` (10 tests, mock `subprocess.run`)

| Test | Covers |
|---|---|
| `test_get_now_playing_success` | Returns formatted artist/title/player string |
| `test_get_now_playing_empty_metadata` | Empty stdout → "Nothing is playing." |
| `test_get_now_playing_no_player` | "No players found" in stderr → "No media player is currently running." |
| `test_media_play_success` | `playerctl play` called, returns "Done." |
| `test_media_pause_success` | `playerctl pause` called, returns "Done." |
| `test_media_next_success` | `playerctl next` called, returns "Done." |
| `test_media_previous_success` | `playerctl previous` called, returns "Done." |
| `test_media_stop_success` | `playerctl stop` called, returns "Done." |
| `test_playerctl_not_installed` | `FileNotFoundError` → install instruction string |
| `test_playerctl_timeout` | `TimeoutExpired` → timeout error string |

## Constraints

- `playerctl` CLI only — no D-Bus/pydbus/dbus-python dependencies.
- All six tool functions are synchronous; no `asyncio` in the module.
- `subprocess.run` with `text=True, capture_output=True, timeout=5` for all calls.
- No new agent, no new LangGraph node, no new entry in `_KNOWN_INTENTS`.
- Media keyword routes go inside the existing `"respond"` list, not as a new dict entry.
