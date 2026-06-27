# Proactive Assistant Design

## Goal

Plia-OS monitors user activity via the Observer and proactively sends helpful, context-aware messages without the user asking — delivered via voice (TTS) and dashboard chat.

## Architecture

`core/proactive.py` — `ProactiveService` singleton with one asyncio loop `_check_loop()` that evaluates 4 trigger conditions every `proactive_check_interval` seconds (default 60). For each condition that fires and clears rate-limit + quiet-hours checks: calls Ollama to generate a 1-2 sentence message, then emits to voice (announcement queue) and dashboard (WebSocket chat).

Depends on `ObserverService`: reads `observer_store` for recent activity and checks `get_observer().is_running()` before each evaluation. If observer is off, check loop skips silently.

Same singleton + `start()`/`stop()` lifecycle pattern as `ObserverService`. Started in `core/main.py` lifespan after observer. `proactive_enabled: bool = False` — opt-in only.

```
ObserverService (observer.db) ──→ ProactiveService._check_loop()
                                        │
                          ┌─────────────┴──────────────┐
                          ▼                            ▼
                   voice announcement queue     WebSocket proactive_message
                   (same path as reminder_fired) (dashboard renders as
                                                  assistant chat bubble)
```

## Triggers

Four trigger types evaluated each loop iteration:

| Trigger | Condition | Default Threshold | Cooldown |
|---|---|---|---|
| `distraction` | Same app focused continuously > N min AND app classified as distracting | 20 min | 30 min |
| `context_switch` | New app held > 30s after focus change | — | 5 min |
| `checkin` | User active in last 10 min AND N min elapsed since last check-in | 120 min | 120 min |
| `anomaly` | Current app+hour combo not seen in observer history (last 7 days) | — | 60 min |

**Distraction classification:** LLM classifies app name as distracting (social media, news, video streaming, games) on first encounter. Result cached in `_distraction_cache: dict[str, bool]` — in-memory only, not persisted. Cache clears on service restart.

**Activity detection (check-in):** User considered active if observer store has any focus event or key event in last 10 minutes.

**Anomaly detection:** Query `focus_events` in observer.db for (app_name, hour_of_day) pairs from last 7 days. If current pair absent → anomaly.

## Rate Limiting

- `_last_fired: dict[str, datetime]` — in-memory, per trigger type
- Per-trigger cooldowns enforced independently (see table above)
- Global cap: maximum 1 proactive message per 5 minutes regardless of trigger
- `_last_message_ts: datetime | None` — tracks global cap

## Message Generation

Rule detects trigger, LLM writes the message:

```
System: You are Plia-OS, a proactive AI assistant. Write a brief, natural,
helpful message (1-2 sentences max) based on the trigger and context below.
Be direct and specific. No filler.

Trigger: <trigger_type>
Current app: <app_name>
Duration: <N minutes> (for distraction trigger)
User profile: <observer profile snippet, max 200 chars>
```

Response used verbatim as the proactive message.

**Cloud guard:** If `cfg.fallback_provider` is set → skip all trigger evaluation and LLM calls. No observer or proactive data leaves the local machine.

## Quiet Hours

`proactive_quiet_hours_start` and `proactive_quiet_hours_end` (hour 0-23, default 0–7).

During quiet hours:
- Voice (TTS) emission suppressed
- Dashboard WebSocket event still emitted (silent notification)
- Rate limits and cooldowns still advance normally

Quiet hours wrap midnight: if start > end (e.g., 22–7), treated as crossing midnight.

## Output Channels

**Voice:** `events.emit("proactive_message", {"text": msg, "trigger": trigger_type})` — voice pipeline subscribes and enqueues in announcement queue (same path as `reminder_fired`). Suppressed during quiet hours.

**Dashboard:** Same `proactive_message` event forwarded over WebSocket. Browser renders as assistant chat bubble with `[Proactive]` badge. Always emitted (quiet hours do not suppress dashboard).

## Config Fields (`core/config.py`)

```python
proactive_enabled: bool = False
proactive_check_interval: int = 60          # seconds between trigger checks
proactive_distraction_threshold: int = 20   # minutes before distraction trigger
proactive_checkin_interval: int = 120       # minutes between scheduled check-ins
proactive_quiet_hours_start: int = 0        # hour 0-23, voice silenced from
proactive_quiet_hours_end: int = 7          # hour 0-23, voice silenced until
```

## `core/proactive.py` Interface

```python
class ProactiveService:
    async def start() -> None
    async def stop() -> None
    def is_running() -> bool
    def last_message_ts() -> str | None
    def last_trigger_type() -> str | None

def get_proactive() -> ProactiveService   # singleton
```

Internal:
- `_check_loop()` — main evaluation loop
- `_evaluate_triggers() -> list[str]` — returns list of triggered trigger names
- `_classify_distraction(app_name: str) -> bool` — LLM call, cached
- `_generate_message(trigger: str, context: dict) -> str` — LLM call
- `_emit_message(text: str, trigger: str) -> None` — handles quiet hours + channel dispatch

## API Endpoints (`dashboard/server.py`)

- `GET /api/proactive/status` → `{enabled, running, last_message_ts, last_trigger_type}`
- `POST /api/proactive/enable` → starts service, sets `proactive_enabled=True`
- `POST /api/proactive/disable` → stops service, sets `proactive_enabled=False`

## Tools (`modules/proactive_tools.py`)

```python
@tool("Get proactive assistant status")
def proactive_status() -> str

@tool("Enable the proactive assistant")
def enable_proactive() -> str

@tool("Disable the proactive assistant")
def disable_proactive() -> str
```

## Keyword Routes (`core/supervisor.py`)

Added to `_KEYWORD_ROUTES["respond"]`:

```python
"enable proactive", "start proactive", "disable proactive", "stop proactive",
"proactive status", "stop interrupting", "pause suggestions", "resume suggestions",
```

## Dashboard (`dashboard/static/index.html`)

New panel after Observer section:
- Enable/disable toggle (`id="proactiveToggleBtn"`)
- Status badge: running / stopped
- Quiet hours: start hour + end hour inputs
- Distraction threshold (minutes input)
- Check-in interval (minutes input)
- Last triggered type + timestamp
- Last message preview (first 200 chars)

WebSocket handler: `if (msg.type === 'proactive_message') { appendChatMessage('assistant', '[Proactive] ' + msg.text); }`

Config fields loaded on page load, saved field-by-field via `POST /api/config`.

## `core/main.py`

```python
async def _start_proactive() -> None:
    try:
        import core.proactive as pro_mod
        await pro_mod.get_proactive().start()
    except Exception as exc:
        from core.config import update_config
        await asyncio.to_thread(update_config, proactive_enabled=False)
        logger.warning("Proactive startup failed, disabled: %s", exc)
```

In lifespan: start after observer, same cancel/await cleanup pattern.

## Testing

`tests/test_proactive.py` — 12+ tests:
- Distraction trigger fires when app focused > threshold
- Distraction trigger suppressed during cooldown
- Context switch trigger fires on new app held > 30s
- Check-in trigger fires when active + interval elapsed
- Check-in trigger suppressed when user inactive
- Anomaly trigger fires for unknown app+hour combo
- Global 5-min cap blocks second message regardless of trigger
- Quiet hours: voice skipped, dashboard event still emitted
- Cloud guard: `fallback_provider` set → no LLM call, no message emitted
- Observer not running → check loop skips silently
- Distraction cache: LLM called once per app, not on repeat
- `enable_proactive()` / `disable_proactive()` update config

`tests/test_proactive_api.py` — 4 tests: status endpoint, enable, disable, stopped state

`tests/test_supervisor.py` additions — proactive keyword routes hit `"respond"`.

All LLM calls mocked via `unittest.mock.patch`. No real observer, xdotool, or TTS in tests.

## Global Constraints

- All data local — no network calls for trigger evaluation or message content (cloud guard enforced)
- Proactive never blocks chat — errors caught per loop iteration
- Observer must be running for proactive to evaluate; fails silently if not
- `proactive_enabled` defaults to `False` — opt-in only
- Follows exact same singleton + asyncio pattern as `core/observer.py`
- Max 1 message per 5 minutes global — not spammy
- Quiet hours suppress voice only; dashboard always receives messages
