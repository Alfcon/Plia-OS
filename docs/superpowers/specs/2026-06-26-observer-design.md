# Observer — User Activity Monitoring Design

## Goal

Continuously capture screen content, window focus, and keystrokes; summarize into a rolling user profile every 5 minutes; inject profile as context into every chat turn so Plia-OS can assist the user better.

## Architecture

Six components:

| Component | Purpose |
|---|---|
| `core/observer.py` | Singleton with 4 asyncio tasks: screen capture, focus tracking, keystroke capture, profile builder |
| `agents/observer_store.py` | SQLite `~/.plia/observer.db` — raw observations + profile cache |
| `modules/observer_tools.py` | `@tool` wrappers: `observer_status`, `enable_observer`, `disable_observer` |
| `core/config.py` | Config fields: `observer_enabled`, intervals, retention |
| `core/main.py` | Start observer on lifespan startup if enabled (same pattern as Tor) |
| `core/supervisor.py` | Inject `get_profile()` into `run_turn()` as system message |

### Data Flow

```
Screenshot (every 30s) → tesseract OCR → screen_obs table
xdotool poll (every 2s) → active window/app → focus_events table
evdev keyboard listener → buffered chunks → key_events table
                                  ↓
                    Profile loop (every 5min)
                    → query last 10min of observations
                    → Ollama summarizes → profile text
                    → stored in profiles table + _profile_text cache
                                  ↓
                    run_turn() → system message injection
```

## Data Capture

### Screen Capture (every 30s)

- Capture via `mss` (`mss.mss().grab(mss.mss().monitors[0])`) — pure Python, no system dep
- OCR via `pytesseract.image_to_string()`
- Skip storage if OCR text identical to previous capture (no change)
- Record active window title and app name alongside OCR text
- Graceful degradation: if `pytesseract` not installed, skip with log warning

### Window/Focus Tracking (every 2s)

- Active window title: `xdotool getactivewindow getwindowname`
- App name: `xdotool getactivewindow getwindowpid` + `/proc/<pid>/comm`
- Track duration: on focus change, store previous window + elapsed seconds
- Graceful degradation: if `xdotool` absent, window title = `"unknown"`

### Keystroke Capture (continuous, evdev)

- Auto-detect keyboard device: scan `/dev/input/event*` for `EV_KEY` capability
- Non-blocking asyncio read via `python-evdev`
- Buffer keypresses → flush every 10s or on window focus change
- Map keycodes to chars (handle shift, backspace, space, enter)
- Store chunk with current window context: `(ts, window_title, app_name, text_chunk)`
- Requires user in `input` group: `sudo usermod -aG input $USER`
- Log setup instruction on first enable if permission denied
- Graceful degradation: if `python-evdev` not installed or permission denied, skip keystroke capture

## Profile Builder

Background asyncio task, fires every 5 minutes:

1. Query `observer_store.get_recent_obs(minutes=10)` — all three tables merged
2. Build summarization prompt:

```
You are summarizing a user's recent computer activity to help an AI assistant understand them better.

Recent activity (last 10 minutes):
SCREEN (30s intervals): <ocr snippets>
FOCUS: <app1 (Ns), app2 (Ns), ...>
TYPED: <key chunks with app context>

Write a 3-5 sentence profile update describing:
- What the user is working on right now
- What apps/sites they are using
- Any notable patterns or context useful for an AI assistant

Be concise and factual. No speculation beyond what the data shows.
```

3. Call Ollama via `call_llm()` → profile text
4. Store to `profiles` table + update in-memory `_profile_text`
5. On error: log and skip; never block chat

**Profile injection in `run_turn()`:**

```python
profile = get_observer().get_profile()
if profile:
    messages = [messages[0],
                {"role": "system", "content": f"User activity context:\n{profile}"},
                *messages[1:]]
```

Profile is ephemeral context — not stored in `memory.db`, only `observer.db`.

## Storage

File: `~/.plia/observer.db`

```sql
CREATE TABLE screen_obs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    window_title TEXT,
    app_name TEXT,
    ocr_text TEXT
);

CREATE TABLE focus_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    window_title TEXT,
    app_name TEXT,
    duration_seconds REAL
);

CREATE TABLE key_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    window_title TEXT,
    app_name TEXT,
    text_chunk TEXT
);

CREATE TABLE profiles (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    profile_text TEXT
);
```

**Retention:** prune rows older than `observer_retention_hours` (default 24) on startup. Profiles kept 7 days.

### `observer_store.py` API

- `get_observer_store()` — singleton accessor
- `add_screen_obs(ts, window_title, app_name, ocr_text)`
- `add_focus_event(ts, window_title, app_name, duration_seconds)`
- `add_key_chunk(ts, window_title, app_name, text_chunk)`
- `get_recent_obs(minutes=10) -> dict` — all three tables merged, sorted by ts
- `save_profile(ts, text)` / `get_latest_profile() -> str | None`
- `prune_old(retention_hours=24)`

## Config Fields (`core/config.py`)

```python
observer_enabled: bool = False
observer_screen_interval: int = 30       # seconds between screen captures
observer_profile_interval: int = 300     # seconds between profile rebuilds
observer_retention_hours: int = 24       # raw obs retention
```

## `core/observer.py` Interface

```python
class ObserverService:
    async def start() -> None
    async def stop() -> None
    def get_profile() -> str        # returns latest _profile_text or ""
    def is_running() -> bool
    def last_capture_ts() -> str | None
    def last_profile_ts() -> str | None

def get_observer() -> ObserverService   # singleton
```

Internal tasks:
- `_screen_loop()` — captures + OCR every `observer_screen_interval` seconds
- `_focus_loop()` — polls active window every 2s
- `_key_loop()` — evdev async event listener
- `_profile_loop()` — rebuilds profile every `observer_profile_interval` seconds

## API Endpoints (`dashboard/server.py`)

- `GET /api/observer/status` → `{enabled, running, last_capture, last_profile, profile_preview}`
- `POST /api/observer/enable` → starts observer, sets `observer_enabled=True` in config
- `POST /api/observer/disable` → stops observer, sets `observer_enabled=False`

## Dashboard

Observer panel in Settings sidebar (same layout as Tor/VPN toggle):
- Enable/disable toggle
- Status badge: running / stopped
- Last capture time
- Profile age
- Profile preview (first 200 chars)

WebSocket event `observer_status` emitted on enable/disable/profile-update.

## Keyword Routes

Added to `_KEYWORD_ROUTES["respond"]` in `core/supervisor.py`:

```python
"enable observer", "start observer", "disable observer", "stop observer",
"observer status", "what am i doing", "what are you tracking",
```

## Optional Dependency Group

`pyproject.toml`:
```toml
[project.optional-dependencies]
observer = ["pytesseract", "python-evdev", "mss"]
```

Install: `pip install -e ".[observer]"`
System dep: `sudo apt install tesseract-ocr`

## Testing

- `tests/test_observer_store.py` — CRUD, prune, get_recent_obs merging
- `tests/test_observer.py` — mock screen/focus/keys; profile prompt construction; `get_profile()` injection into `run_turn()`; graceful degradation when deps missing
- `tests/test_observer_api.py` — enable/disable/status endpoints

No real evdev, X11, or tesseract calls in tests — all mocked via `unittest.mock.patch`.

## Global Constraints

- All data stays local — no network calls for observation data
- Observer never blocks chat — all errors caught per loop iteration
- Graceful degradation: each capture type (screen/focus/keys) fails independently
- `observer.db` separate from `memory.db` — raw high-volume data isolated
- Follows exact same singleton + asyncio pattern as `core/tor_manager.py`
- Optional deps: observer features disabled if packages not installed
- `observer_enabled` defaults to `False` — opt-in only
