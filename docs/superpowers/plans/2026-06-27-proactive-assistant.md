# Proactive Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `ProactiveService` that evaluates 4 trigger conditions against observer data every 60 seconds and sends context-aware messages to the user via voice (TTS announcement queue) and dashboard chat.

**Architecture:** `core/proactive.py` is a singleton service with the same `start()`/`stop()` lifecycle pattern as `core/observer.py`. It reads from `observer_store` and calls Ollama via `call_llm()` — never an external provider (cloud guard matches observer). Messages are emitted as `proactive_message` events: voice pipeline enqueues them like reminders, dashboard renders them as chat bubbles. `proactive_enabled` defaults to `False` (opt-in).

**Tech Stack:** Python 3.12, asyncio, SQLite (`~/.plia/observer.db` via existing `ObserverStore`), FastAPI, LangGraph event bus (`core/events.py`), existing `agents.llm.call_llm`.

## Global Constraints

- All data stays local — cloud guard: if `cfg.fallback_provider` is set, skip all trigger evaluation and LLM calls
- `proactive_enabled: bool = False` — opt-in only, never auto-enable
- Observer must be running; if `get_observer().is_running()` is False, skip check loop iteration silently
- Max 1 proactive message per 5 minutes global (`_GLOBAL_COOLDOWN = 300`)
- Per-trigger cooldowns: `distraction=1800s`, `context_switch=300s`, `checkin=7200s`, `anomaly=3600s`
- `_CONTEXT_SWITCH_HOLD = 30` — seconds on new app before context_switch fires
- Quiet hours suppress voice only; dashboard `proactive_message` event always emitted
- Quiet hours default: start=0, end=7 (0:00–7:00 UTC); midnight-wrap logic required
- Follows exact same singleton + asyncio pattern as `core/observer.py`
- `_start_proactive()` in `core/main.py` must call `update_config(proactive_enabled=False)` on startup failure
- No new database — reads existing `observer.db` tables via `ObserverStore`

---

### Task 1: Config Fields + Observer Store Anomaly Query

**Files:**
- Modify: `core/config.py` (after `observer_retention_hours` field, ~line 102)
- Modify: `agents/observer_store.py` (add method after `get_latest_profile`)
- Test: `tests/test_observer_store.py` (append 3 tests)
- Test: `tests/test_proactive.py` (create, config tests only)

**Interfaces:**
- Produces: `PliaConfig.proactive_enabled: bool`, `PliaConfig.proactive_check_interval: int`, `PliaConfig.proactive_distraction_threshold: int`, `PliaConfig.proactive_checkin_interval: int`, `PliaConfig.proactive_quiet_hours_start: int`, `PliaConfig.proactive_quiet_hours_end: int`
- Produces: `ObserverStore.get_app_hour_history(days: int = 7) -> list[tuple[str, int]]` — returns `(app_name, hour_of_day)` pairs from `focus_events` within last N days

- [ ] **Step 1: Write failing config test**

Create `tests/test_proactive.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


def test_proactive_config_defaults():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.proactive_enabled is False
    assert cfg.proactive_check_interval == 60
    assert cfg.proactive_distraction_threshold == 20
    assert cfg.proactive_checkin_interval == 120
    assert cfg.proactive_quiet_hours_start == 0
    assert cfg.proactive_quiet_hours_end == 7
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/alfcon/Projects/Plia-OS && source .venv/bin/activate
pytest tests/test_proactive.py::test_proactive_config_defaults -v
```

Expected: FAIL — `PliaConfig` has no `proactive_enabled` attribute.

- [ ] **Step 3: Add config fields**

In `core/config.py`, after `observer_retention_hours: int = 24` (around line 102), add:

```python
    # Proactive assistant — observer-triggered suggestions
    proactive_enabled: bool = False
    proactive_check_interval: int = 60          # seconds between trigger checks
    proactive_distraction_threshold: int = 20   # minutes before distraction trigger
    proactive_checkin_interval: int = 120       # minutes between scheduled check-ins
    proactive_quiet_hours_start: int = 0        # hour 0-23, voice silenced from
    proactive_quiet_hours_end: int = 7          # hour 0-23, voice silenced until
```

- [ ] **Step 4: Run config test to verify it passes**

```bash
pytest tests/test_proactive.py::test_proactive_config_defaults -v
```

Expected: PASS

- [ ] **Step 5: Write failing observer_store tests**

Append to `tests/test_observer_store.py`:

```python
def test_get_app_hour_history_empty(tmp_path):
    from agents.observer_store import ObserverStore
    s = ObserverStore(str(tmp_path / "obs.db"))
    assert s.get_app_hour_history(days=7) == []


def test_get_app_hour_history_returns_tuples(tmp_path):
    from agents.observer_store import ObserverStore
    from datetime import datetime, timezone
    s = ObserverStore(str(tmp_path / "obs.db"))
    ts = datetime.now(timezone.utc).isoformat()
    s.add_focus_event(ts, "Terminal", "firefox", 10.0)
    result = s.get_app_hour_history(days=7)
    assert len(result) == 1
    app_name, hour = result[0]
    assert app_name == "firefox"
    assert 0 <= hour <= 23


def test_get_app_hour_history_filters_old(tmp_path):
    from agents.observer_store import ObserverStore
    from datetime import datetime, timezone, timedelta
    s = ObserverStore(str(tmp_path / "obs.db"))
    old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    s.add_focus_event(old_ts, "Window", "firefox", 10.0)
    assert s.get_app_hour_history(days=7) == []
```

- [ ] **Step 6: Run observer_store tests to verify they fail**

```bash
pytest tests/test_observer_store.py::test_get_app_hour_history_empty tests/test_observer_store.py::test_get_app_hour_history_returns_tuples tests/test_observer_store.py::test_get_app_hour_history_filters_old -v
```

Expected: FAIL — `ObserverStore` has no `get_app_hour_history`.

- [ ] **Step 7: Implement `get_app_hour_history`**

In `agents/observer_store.py`, after `get_latest_profile` method (around line 122), add:

```python
    def get_app_hour_history(self, days: int = 7) -> list[tuple[str, int]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT app_name, CAST(strftime('%H', ts) AS INTEGER) "
                "FROM focus_events WHERE ts >= ? AND app_name IS NOT NULL",
                (cutoff,),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]
```

- [ ] **Step 8: Run all observer_store and config tests**

```bash
pytest tests/test_observer_store.py tests/test_proactive.py -v
```

Expected: all PASS

- [ ] **Step 9: Run full suite to check no regressions**

```bash
pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add core/config.py agents/observer_store.py tests/test_observer_store.py tests/test_proactive.py
git commit -m "feat(proactive): add config fields and observer_store anomaly query"
```

---

### Task 2: ProactiveService Core

**Files:**
- Create: `core/proactive.py`
- Test: `tests/test_proactive.py` (append bulk of tests)

**Interfaces:**
- Consumes: `PliaConfig.proactive_*` fields (Task 1), `ObserverStore.get_app_hour_history` (Task 1), `ObserverStore.get_recent_obs`, `ObserverService.is_running()`, `ObserverService._current_app`, `ObserverService._current_window`, `ObserverService.get_profile()`
- Produces: `ProactiveService` class with `start()`, `stop()`, `is_running() -> bool`, `last_message_ts() -> str | None`, `last_trigger_type() -> str | None`
- Produces: `get_proactive() -> ProactiveService` singleton

- [ ] **Step 1: Write failing singleton test**

Append to `tests/test_proactive.py`:

```python
def test_proactive_singleton():
    import core.proactive as pm
    pm._proactive = None
    s1 = pm.get_proactive()
    s2 = pm.get_proactive()
    assert s1 is s2
    pm._proactive = None


def test_proactive_not_running_by_default():
    import core.proactive as pm
    pm._proactive = None
    pro = pm.get_proactive()
    assert pro.is_running() is False
    assert pro.last_message_ts() is None
    assert pro.last_trigger_type() is None
    pm._proactive = None
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_proactive.py::test_proactive_singleton tests/test_proactive.py::test_proactive_not_running_by_default -v
```

Expected: FAIL — `core.proactive` module not found.

- [ ] **Step 3: Create `core/proactive.py`**

```python
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_proactive: "ProactiveService | None" = None

_TRIGGER_COOLDOWNS: dict[str, int] = {
    "distraction": 1800,   # 30 min
    "context_switch": 300, # 5 min
    "checkin": 7200,       # 120 min
    "anomaly": 3600,       # 60 min
}
_GLOBAL_COOLDOWN = 300    # 5 min between any messages
_CONTEXT_SWITCH_HOLD = 30 # seconds on new app before context_switch fires


class ProactiveService:
    def __init__(self) -> None:
        from core.config import get_config
        cfg = get_config()
        self._check_interval: int = cfg.proactive_check_interval
        self._distraction_threshold: int = cfg.proactive_distraction_threshold
        self._checkin_interval: int = cfg.proactive_checkin_interval
        self._quiet_start: int = cfg.proactive_quiet_hours_start
        self._quiet_end: int = cfg.proactive_quiet_hours_end
        self._last_fired: dict[str, datetime] = {}
        self._last_message_ts: datetime | None = None
        self._last_trigger_type: str | None = None
        self._distraction_cache: dict[str, bool] = {}
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._check_loop())]
        logger.info("ProactiveService started")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        logger.info("ProactiveService stopped")

    def is_running(self) -> bool:
        return bool(self._tasks) and any(not t.done() for t in self._tasks)

    def last_message_ts(self) -> str | None:
        return self._last_message_ts.isoformat() if self._last_message_ts else None

    def last_trigger_type(self) -> str | None:
        return self._last_trigger_type

    async def _check_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._check_interval)
                await self._run_check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Proactive check error")

    async def _run_check_once(self) -> None:
        from core.config import get_config
        cfg = get_config()
        if cfg.fallback_provider:
            return

        try:
            from core.observer import get_observer
            if not get_observer().is_running():
                return
        except Exception:
            return

        now = datetime.now(timezone.utc)
        if self._last_message_ts:
            if (now - self._last_message_ts).total_seconds() < _GLOBAL_COOLDOWN:
                return

        triggers = await self._evaluate_triggers()
        if not triggers:
            return

        chosen = None
        for trigger in triggers:
            last = self._last_fired.get(trigger)
            if last is None or (now - last).total_seconds() >= _TRIGGER_COOLDOWNS[trigger]:
                chosen = trigger
                break

        if chosen is None:
            return

        context = await self._build_context(chosen)
        text = await self._generate_message(chosen, context)
        if not text:
            return

        self._last_fired[chosen] = now
        self._last_message_ts = now
        self._last_trigger_type = chosen
        await self._emit_message(text, chosen)

    async def _evaluate_triggers(self) -> list[str]:
        try:
            from core.observer import get_observer
            obs = get_observer()
            app = obs._current_app or ""
        except Exception:
            return []

        from agents.observer_store import get_observer_store
        store = get_observer_store()
        window = self._distraction_threshold + 5
        recent = await asyncio.to_thread(store.get_recent_obs, window)
        focus_events = recent.get("focus", [])
        now = datetime.now(timezone.utc)
        triggers: list[str] = []

        # distraction: same app focused longer than threshold
        threshold_secs = self._distraction_threshold * 60
        current_duration = sum(
            e["duration_seconds"] for e in focus_events if e["app_name"] == app
        )
        if app and current_duration >= threshold_secs:
            if await self._classify_distraction(app):
                triggers.append("distraction")

        # context_switch: switched to new app > HOLD seconds ago
        if focus_events:
            last_event = focus_events[-1]
            last_ts = datetime.fromisoformat(last_event["ts"])
            held = (now - last_ts).total_seconds()
            if last_event["app_name"] != app and held >= _CONTEXT_SWITCH_HOLD:
                triggers.append("context_switch")

        # checkin: active recently + interval elapsed
        has_activity = bool(recent.get("keys") or focus_events)
        last_checkin = self._last_fired.get("checkin")
        checkin_secs = self._checkin_interval * 60
        if has_activity and (
            last_checkin is None
            or (now - last_checkin).total_seconds() >= checkin_secs
        ):
            triggers.append("checkin")

        # anomaly: current (app, hour) not seen in last 7 days
        if app:
            history = await asyncio.to_thread(store.get_app_hour_history, 7)
            known = set(history)
            if (app, now.hour) not in known:
                triggers.append("anomaly")

        return triggers

    async def _classify_distraction(self, app_name: str) -> bool:
        if app_name in self._distraction_cache:
            return self._distraction_cache[app_name]
        try:
            from agents.llm import call_llm
            msg = await call_llm([
                {"role": "system", "content": "Answer only yes or no."},
                {"role": "user", "content": (
                    f"Is '{app_name}' typically a distracting application "
                    "(social media, news, video streaming, gaming, entertainment)?"
                )},
            ])
            result = (msg.get("content") or "").strip().lower().startswith("y")
        except Exception:
            logger.exception("Distraction classification error")
            result = False
        self._distraction_cache[app_name] = result
        return result

    async def _build_context(self, trigger: str) -> dict:
        try:
            from core.observer import get_observer
            obs = get_observer()
            return {
                "trigger": trigger,
                "app": obs._current_app or "unknown",
                "window": obs._current_window or "unknown",
                "profile": obs.get_profile()[:200],
            }
        except Exception:
            return {"trigger": trigger, "app": "unknown", "window": "unknown", "profile": ""}

    async def _generate_message(self, trigger: str, context: dict) -> str:
        try:
            from agents.llm import call_llm
            prompt = (
                f"Trigger: {context['trigger']}\n"
                f"Current app: {context['app']}\n"
                f"Window title: {context['window']}\n"
                f"User profile: {context['profile']}\n\n"
                "Write a brief, natural, helpful 1-2 sentence message to the user. "
                "Be specific and direct. No filler."
            )
            msg = await call_llm([
                {
                    "role": "system",
                    "content": (
                        "You are Plia-OS, a proactive AI assistant. "
                        "Write concise, helpful messages based on what the user is doing."
                    ),
                },
                {"role": "user", "content": prompt},
            ])
            return (msg.get("content") or "").strip()
        except Exception:
            logger.exception("Proactive message generation error")
            return ""

    async def _emit_message(self, text: str, trigger: str) -> None:
        from core import events
        now_hour = datetime.now(timezone.utc).hour
        qs, qe = self._quiet_start, self._quiet_end
        if qs <= qe:
            in_quiet = qs <= now_hour < qe
        else:
            in_quiet = now_hour >= qs or now_hour < qe
        await events.emit("proactive_message", {
            "text": text,
            "trigger": trigger,
            "voice": not in_quiet,
        })
        logger.info("Proactive [%s]: %s", trigger, text[:80])


def get_proactive() -> ProactiveService:
    global _proactive
    if _proactive is None:
        _proactive = ProactiveService()
    return _proactive
```

- [ ] **Step 4: Run singleton tests to verify they pass**

```bash
pytest tests/test_proactive.py::test_proactive_singleton tests/test_proactive.py::test_proactive_not_running_by_default -v
```

Expected: PASS

- [ ] **Step 5: Write remaining core tests**

Append to `tests/test_proactive.py`:

```python
@pytest.fixture
def pro():
    import core.proactive as pm
    pm._proactive = None
    svc = pm.get_proactive()
    yield svc
    pm._proactive = None


@pytest.mark.asyncio
async def test_start_stop(pro):
    with patch.object(pro, '_check_loop', new_callable=AsyncMock):
        await pro.start()
        assert pro.is_running() is True
        await pro.stop()
        assert pro.is_running() is False


@pytest.mark.asyncio
async def test_cloud_guard_skips(pro):
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg:
        mock_cfg.return_value = MagicMock(fallback_provider='openai')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_observer_not_running_skips(pro):
    mock_obs = MagicMock(is_running=MagicMock(return_value=False))
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_global_cooldown_blocks(pro):
    pro._last_message_ts = datetime.now(timezone.utc)
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_per_trigger_cooldown_blocks(pro):
    now = datetime.now(timezone.utc)
    pro._last_fired['checkin'] = now
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_emit = AsyncMock()
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs), \
         patch.object(pro, '_evaluate_triggers', AsyncMock(return_value=['checkin'])), \
         patch.object(pro, '_generate_message', AsyncMock(return_value='hi')), \
         patch.object(pro, '_emit_message', mock_emit):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        await pro._run_check_once()
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_message_sent_updates_state(pro):
    now = datetime.now(timezone.utc)
    pro._last_message_ts = now - timedelta(seconds=400)  # past global cooldown
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_emit = AsyncMock()
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs), \
         patch.object(pro, '_evaluate_triggers', AsyncMock(return_value=['checkin'])), \
         patch.object(pro, '_build_context', AsyncMock(return_value={'trigger': 'checkin', 'app': 'code', 'window': 'x', 'profile': ''})), \
         patch.object(pro, '_generate_message', AsyncMock(return_value='Time for a break!')), \
         patch.object(pro, '_emit_message', mock_emit):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        await pro._run_check_once()
    mock_emit.assert_called_once()
    assert pro.last_trigger_type() == 'checkin'
    assert pro.last_message_ts() is not None


@pytest.mark.asyncio
async def test_quiet_hours_suppresses_voice(pro):
    pro._quiet_start = 0
    pro._quiet_end = 23  # essentially always quiet
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    with patch('core.proactive.events.emit', side_effect=fake_emit):
        await pro._emit_message('hello', 'checkin')
    assert len(emitted) == 1
    assert emitted[0]['voice'] is False
    assert emitted[0]['text'] == 'hello'


@pytest.mark.asyncio
async def test_non_quiet_hours_voice_on(pro):
    pro._quiet_start = 0
    pro._quiet_end = 0  # zero-length window, never quiet
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    with patch('core.proactive.events.emit', side_effect=fake_emit):
        await pro._emit_message('hello', 'checkin')
    assert emitted[0]['voice'] is True


@pytest.mark.asyncio
async def test_midnight_wrap_quiet_hours(pro):
    # quiet from 22:00 to 07:00
    pro._quiet_start = 22
    pro._quiet_end = 7
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    # patch datetime.now to return hour=23 (inside quiet window)
    fake_now = MagicMock()
    fake_now.hour = 23
    with patch('core.proactive.datetime') as mock_dt, \
         patch('core.proactive.events.emit', side_effect=fake_emit):
        mock_dt.now.return_value = fake_now
        await pro._emit_message('hello', 'checkin')
    assert emitted[0]['voice'] is False


@pytest.mark.asyncio
async def test_distraction_cache_llm_called_once(pro):
    call_count = 0
    async def fake_llm(messages, **_):
        nonlocal call_count
        call_count += 1
        return {'content': 'yes'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        await pro._classify_distraction('reddit')
        await pro._classify_distraction('reddit')
    assert call_count == 1
    assert pro._distraction_cache['reddit'] is True


@pytest.mark.asyncio
async def test_distraction_cache_non_distracting(pro):
    async def fake_llm(messages, **_):
        return {'content': 'no'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        result = await pro._classify_distraction('code')
    assert result is False
    assert pro._distraction_cache['code'] is False


@pytest.mark.asyncio
async def test_generate_message_returns_llm_content(pro):
    async def fake_llm(messages, **_):
        return {'content': 'You have been on Reddit for 20 minutes.'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        text = await pro._generate_message('distraction', {'trigger': 'distraction', 'app': 'reddit', 'window': 'Reddit', 'profile': ''})
    assert text == 'You have been on Reddit for 20 minutes.'


@pytest.mark.asyncio
async def test_generate_message_returns_empty_on_error(pro):
    async def fail_llm(messages, **_):
        raise RuntimeError("LLM down")
    with patch('agents.llm.call_llm', side_effect=fail_llm):
        text = await pro._generate_message('checkin', {'trigger': 'checkin', 'app': 'code', 'window': 'x', 'profile': ''})
    assert text == ''
```

- [ ] **Step 6: Run all proactive tests**

```bash
pytest tests/test_proactive.py -v
```

Expected: all PASS

- [ ] **Step 7: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add core/proactive.py tests/test_proactive.py
git commit -m "feat(proactive): add ProactiveService with triggers, rate limiting, and quiet hours"
```

---

### Task 3: Voice Integration + API Endpoints + Tools

**Files:**
- Modify: `voice/pipeline.py` (add `proactive_message` handler in `_on_event`)
- Create: `modules/proactive_tools.py`
- Modify: `dashboard/server.py` (add 3 endpoints after observer endpoints, before `/api/token-usage`)
- Test: `tests/test_proactive_api.py` (create)
- Test: `tests/test_proactive.py` (append voice pipeline test)

**Interfaces:**
- Consumes: `get_proactive() -> ProactiveService` (Task 2), `PliaConfig.proactive_*` fields (Task 1)
- Produces: `GET /api/proactive/status`, `POST /api/proactive/enable`, `POST /api/proactive/disable`
- Produces: `@tool` functions `proactive_status`, `enable_proactive`, `disable_proactive`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_proactive_api.py`:

```python
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_proactive():
    pro = MagicMock()
    pro.is_running.return_value = False
    pro.last_message_ts.return_value = None
    pro.last_trigger_type.return_value = None
    return pro


@pytest.mark.asyncio
async def test_proactive_status_stopped(mock_proactive):
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.get('/api/proactive/status')
    assert r.status_code == 200
    data = r.json()
    assert data['enabled'] is False
    assert data['running'] is False
    assert data['last_message_ts'] is None
    assert data['last_trigger_type'] is None


@pytest.mark.asyncio
async def test_proactive_enable(mock_proactive):
    mock_proactive.is_running.return_value = False
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.post('/api/proactive/enable')
    assert r.status_code == 200
    assert r.json()['success'] is True


@pytest.mark.asyncio
async def test_proactive_disable(mock_proactive):
    mock_proactive.is_running.return_value = True
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.post('/api/proactive/disable')
    assert r.status_code == 200
    assert r.json()['success'] is True


@pytest.mark.asyncio
async def test_proactive_status_config_fields(mock_proactive):
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.get('/api/proactive/status')
    data = r.json()
    assert 'quiet_hours_start' in data
    assert 'quiet_hours_end' in data
    assert 'distraction_threshold' in data
    assert 'checkin_interval' in data
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_proactive_api.py -v
```

Expected: FAIL — endpoints not found (404).

- [ ] **Step 3: Add voice pipeline handler**

In `voice/pipeline.py`, in the `_on_event` method, after the `elif payload.get("type") == "speak":` block (around line 77), add:

```python
        elif payload.get("type") == "proactive_message":
            if payload.get("voice", True):
                message = payload.get("text") or ""
                if message:
                    try:
                        self._announcement_queue.put_nowait(message)
                        logger.info("Queued proactive announcement: %s", message)
                    except asyncio.QueueFull:
                        logger.warning("Announcement queue full; dropping proactive: %s", message)
```

- [ ] **Step 4: Write voice pipeline test**

Append to `tests/test_proactive.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_enqueues_proactive_voice():
    from unittest.mock import MagicMock, AsyncMock
    import asyncio
    queue = asyncio.Queue(maxsize=50)
    pipeline = MagicMock()
    pipeline._announcement_queue = queue
    pipeline._on_event = None

    # Import and bind the real _on_event
    from voice.pipeline import VoicePipeline
    with patch('voice.pipeline.get_config') as mock_cfg, \
         patch('voice.pipeline.get_stt_service'), \
         patch('voice.pipeline.get_tts_service'), \
         patch('agents.chat_history.get_recent', return_value=[]):
        mock_cfg.return_value = MagicMock(system_prompt='', stt_model_size='tiny', stt_language='en')
        vp = VoicePipeline.__new__(VoicePipeline)
        vp._announcement_queue = asyncio.Queue(maxsize=50)
        await vp._on_event({'type': 'proactive_message', 'text': 'hello', 'voice': True})
        assert not vp._announcement_queue.empty()
        msg = vp._announcement_queue.get_nowait()
        assert msg == 'hello'


@pytest.mark.asyncio
async def test_pipeline_skips_proactive_when_voice_false():
    import asyncio
    from unittest.mock import MagicMock, patch
    with patch('voice.pipeline.get_config') as mock_cfg, \
         patch('voice.pipeline.get_stt_service'), \
         patch('voice.pipeline.get_tts_service'), \
         patch('agents.chat_history.get_recent', return_value=[]):
        mock_cfg.return_value = MagicMock(system_prompt='', stt_model_size='tiny', stt_language='en')
        from voice.pipeline import VoicePipeline
        vp = VoicePipeline.__new__(VoicePipeline)
        vp._announcement_queue = asyncio.Queue(maxsize=50)
        await vp._on_event({'type': 'proactive_message', 'text': 'hello', 'voice': False})
        assert vp._announcement_queue.empty()
```

- [ ] **Step 5: Add API endpoints to `dashboard/server.py`**

After the observer disable endpoint (after line 1017, before `@router.get("/api/token-usage")`), add:

```python
@router.get("/api/proactive/status")
async def get_proactive_status():
    import core.proactive as pro_mod
    pro = pro_mod.get_proactive()
    cfg = get_config()
    return {
        "enabled": cfg.proactive_enabled,
        "running": pro.is_running(),
        "last_message_ts": pro.last_message_ts(),
        "last_trigger_type": pro.last_trigger_type(),
        "quiet_hours_start": cfg.proactive_quiet_hours_start,
        "quiet_hours_end": cfg.proactive_quiet_hours_end,
        "distraction_threshold": cfg.proactive_distraction_threshold,
        "checkin_interval": cfg.proactive_checkin_interval,
    }


@router.post("/api/proactive/enable")
async def post_proactive_enable():
    import core.proactive as pro_mod
    import core.config as cfg_mod
    pro = pro_mod.get_proactive()
    if not pro.is_running():
        asyncio.create_task(pro.start())
    cfg_mod.update_config(proactive_enabled=True)
    await events.emit("proactive_status", {"enabled": True, "running": True})
    return {"success": True, "message": "Proactive assistant enabled"}


@router.post("/api/proactive/disable")
async def post_proactive_disable():
    import core.proactive as pro_mod
    import core.config as cfg_mod
    pro = pro_mod.get_proactive()
    if pro.is_running():
        asyncio.create_task(pro.stop())
    cfg_mod.update_config(proactive_enabled=False)
    await events.emit("proactive_status", {"enabled": False, "running": False})
    return {"success": True, "message": "Proactive assistant disabled"}
```

- [ ] **Step 6: Create `modules/proactive_tools.py`**

```python
import asyncio
import core.proactive as _pro_mod
from core.registry import tool


@tool("Get proactive assistant status: whether running, last trigger type, and last message time.")
def proactive_status() -> str:
    pro = _pro_mod.get_proactive()
    running = pro.is_running()
    last_ts = pro.last_message_ts() or "never"
    last_trig = pro.last_trigger_type() or "none"
    status = "running" if running else "stopped"
    return f"Proactive assistant: {status}\nLast trigger: {last_trig}\nLast message: {last_ts}"


@tool("Enable the proactive assistant: starts sending context-aware suggestions via voice and chat.")
def enable_proactive() -> str:
    from core.config import update_config
    pro = _pro_mod.get_proactive()
    update_config(proactive_enabled=True)
    if not pro.is_running():
        try:
            asyncio.get_running_loop().create_task(pro.start())
        except RuntimeError:
            pass
    return "Proactive assistant enabled."


@tool("Disable the proactive assistant: stops all unprompted suggestions.")
def disable_proactive() -> str:
    from core.config import update_config
    pro = _pro_mod.get_proactive()
    update_config(proactive_enabled=False)
    if pro.is_running():
        try:
            asyncio.get_running_loop().create_task(pro.stop())
        except RuntimeError:
            pass
    return "Proactive assistant disabled."
```

- [ ] **Step 7: Run all tests**

```bash
pytest tests/test_proactive.py tests/test_proactive_api.py -v
```

Expected: all PASS

- [ ] **Step 8: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add voice/pipeline.py modules/proactive_tools.py dashboard/server.py tests/test_proactive_api.py tests/test_proactive.py
git commit -m "feat(proactive): add voice integration, API endpoints, and tools"
```

---

### Task 4: main.py Lifespan + Supervisor Keywords + Dashboard UI

**Files:**
- Modify: `core/main.py` (add `_start_proactive` + lifespan wiring)
- Modify: `core/supervisor.py` (add keyword routes)
- Modify: `dashboard/static/index.html` (nav button, panel, JS, WebSocket handler)
- Test: `tests/test_supervisor.py` (append routing tests)

**Interfaces:**
- Consumes: `get_proactive() -> ProactiveService` (Task 2), `PliaConfig.proactive_enabled` (Task 1)
- Consumes: `POST /api/proactive/enable`, `POST /api/proactive/disable` (Task 3) — wired into dashboard JS

- [ ] **Step 1: Write failing supervisor routing tests**

Find the existing supervisor test file:
```bash
grep -n "def test_supervisor" tests/test_supervisor.py | head -5
```

Append to `tests/test_supervisor.py`:

```python
def test_proactive_keywords_route_to_respond():
    from core.supervisor import _keyword_route
    assert _keyword_route("enable proactive") == "respond"
    assert _keyword_route("disable proactive") == "respond"
    assert _keyword_route("proactive status") == "respond"
    assert _keyword_route("stop interrupting me") == "respond"
    assert _keyword_route("pause suggestions") == "respond"
    assert _keyword_route("resume suggestions") == "respond"
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_supervisor.py::test_proactive_keywords_route_to_respond -v
```

Expected: FAIL — keywords not in `_KEYWORD_ROUTES`.

- [ ] **Step 3: Add keyword routes to `core/supervisor.py`**

In `core/supervisor.py`, in `_KEYWORD_ROUTES["respond"]` list (around line 116, after the observer entries), add:

```python
                "enable proactive", "start proactive", "disable proactive", "stop proactive",
                "proactive status", "stop interrupting", "pause suggestions", "resume suggestions",
```

- [ ] **Step 4: Run supervisor test to verify it passes**

```bash
pytest tests/test_supervisor.py::test_proactive_keywords_route_to_respond -v
```

Expected: PASS

- [ ] **Step 5: Add `_start_proactive` to `core/main.py`**

In `core/main.py`, after the `_start_observer` function (around line 30), add:

```python
async def _start_proactive() -> None:
    try:
        import core.proactive as pro_mod
        await pro_mod.get_proactive().start()
    except Exception as exc:
        from core.config import update_config
        await asyncio.to_thread(update_config, proactive_enabled=False)
        logger.warning("Proactive assistant startup failed, disabled: %s", exc)
```

- [ ] **Step 6: Wire proactive into lifespan**

In `core/main.py`, inside the `lifespan` function, after the observer task block (after `if get_config().observer_enabled:`), add:

```python
        # Start Proactive assistant if previously enabled
        proactive_activity_task = None
        if get_config().proactive_enabled:
            proactive_activity_task = asyncio.create_task(_start_proactive())
```

After the `yield`, in the cleanup section, add (after the observer cancel block):

```python
        if proactive_activity_task and not proactive_activity_task.done():
            proactive_activity_task.cancel()
```

Also add `proactive_activity_task` to the `filter(None, (...))` await tuple. The existing line is:
```python
        for task in filter(None, (pipeline_task, reminder_task, cron_task, proactive_task, tor_task, observer_task)):
```
Change it to:
```python
        for task in filter(None, (pipeline_task, reminder_task, cron_task, proactive_task, tor_task, observer_task, proactive_activity_task)):
```

- [ ] **Step 7: Add dashboard nav button**

In `dashboard/static/index.html`, find the Observer nav button line:
```
<button class="m-nav-btn" data-section="observer" onclick="showMenuSection('observer');loadObserverStatus()">Observer</button>
```

After it, add:
```html
        <button class="m-nav-btn" data-section="proactive" onclick="showMenuSection('proactive');loadProactiveStatus()">Proactive</button>
```

- [ ] **Step 8: Add dashboard panel HTML**

In `dashboard/static/index.html`, find the closing `</div>` of `m-section-observer` (around line 1309), and after it (before the outer `</div>`) add:

```html
        <div id="m-section-proactive" class="m-pane" style="display:none">
          <div class="settings-section">
            <h3 style="margin:0 0 8px;font-size:13px;color:#aaa;text-transform:uppercase;letter-spacing:.05em">Proactive Assistant</h3>
            <p style="font-size:11px;color:#666;margin:0 0 10px">Monitors activity and sends helpful suggestions via voice and chat. Requires Observer running.</p>
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
              <span style="font-size:13px;color:#ccc">Proactive</span>
              <button id="proactiveToggleBtn" onclick="toggleProactive()"
                style="padding:4px 14px;border-radius:4px;border:1px solid #444;background:#222;color:#ccc;cursor:pointer;font-size:12px">
                Loading…
              </button>
            </div>
            <div id="proactiveStatus" style="font-size:12px;color:#888;padding-left:2px;margin-bottom:6px">Checking…</div>
            <div style="font-size:11px;color:#666;margin-bottom:4px">Last trigger: <span id="proactiveLastTrigger">—</span></div>
            <div style="font-size:11px;color:#666;margin-bottom:10px">Last message: <span id="proactiveLastMessage">—</span></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;color:#aaa">
              <label>Quiet start (0-23)
                <input type="number" id="proactiveQuietStart" min="0" max="23"
                  style="width:100%;margin-top:4px;background:#111;border:1px solid #333;color:#ccc;border-radius:3px;padding:3px 6px"
                  onchange="saveProactiveConfig()">
              </label>
              <label>Quiet end (0-23)
                <input type="number" id="proactiveQuietEnd" min="0" max="23"
                  style="width:100%;margin-top:4px;background:#111;border:1px solid #333;color:#ccc;border-radius:3px;padding:3px 6px"
                  onchange="saveProactiveConfig()">
              </label>
              <label>Distraction threshold (min)
                <input type="number" id="proactiveDistractionThreshold" min="5" max="120"
                  style="width:100%;margin-top:4px;background:#111;border:1px solid #333;color:#ccc;border-radius:3px;padding:3px 6px"
                  onchange="saveProactiveConfig()">
              </label>
              <label>Check-in interval (min)
                <input type="number" id="proactiveCheckinInterval" min="30" max="480"
                  style="width:100%;margin-top:4px;background:#111;border:1px solid #333;color:#ccc;border-radius:3px;padding:3px 6px"
                  onchange="saveProactiveConfig()">
              </label>
            </div>
          </div>
        </div>
```

- [ ] **Step 9: Add WebSocket handler**

In `dashboard/static/index.html`, find:
```javascript
    if (msg.type === 'observer_status') {
      updateObserverUI(msg);
    }
```

After it, add:
```javascript
    if (msg.type === 'proactive_status') {
      updateProactiveUI(msg);
    }
    if (msg.type === 'proactive_message') {
      _appendMsg('assistant', '[Proactive] ' + msg.text);
    }
```

- [ ] **Step 10: Add JavaScript functions**

In `dashboard/static/index.html`, find the `loadObserverStatus` function area (around line 3488). After the `toggleObserver` function, add:

```javascript
  async function loadProactiveStatus() {
    try {
      const r = await fetch('/api/proactive/status');
      const s = await r.json();
      updateProactiveUI(s);
      document.getElementById('proactiveQuietStart').value = s.quiet_hours_start ?? 0;
      document.getElementById('proactiveQuietEnd').value = s.quiet_hours_end ?? 7;
      document.getElementById('proactiveDistractionThreshold').value = s.distraction_threshold ?? 20;
      document.getElementById('proactiveCheckinInterval').value = s.checkin_interval ?? 120;
    } catch(e) {
      const el = document.getElementById('proactiveStatus');
      if (el) el.textContent = 'Status unavailable';
    }
  }

  function updateProactiveUI(s) {
    const btn = document.getElementById('proactiveToggleBtn');
    const status = document.getElementById('proactiveStatus');
    if (!btn) return;
    btn.textContent = s.enabled ? 'Disable' : 'Enable';
    status.textContent = s.running ? 'Running' : 'Stopped';
    status.style.color = s.running ? '#a6e3a1' : '#888';
    const lastTrig = document.getElementById('proactiveLastTrigger');
    const lastMsg = document.getElementById('proactiveLastMessage');
    if (lastTrig) lastTrig.textContent = s.last_trigger_type || '—';
    if (lastMsg) lastMsg.textContent = s.last_message_ts || '—';
  }

  async function toggleProactive() {
    const btn = document.getElementById('proactiveToggleBtn');
    const current = btn.textContent.trim();
    try {
      const endpoint = current === 'Enable' ? '/api/proactive/enable' : '/api/proactive/disable';
      const r = await fetch(endpoint, {method: 'POST'});
      const data = await r.json();
      if (!data.success) {
        document.getElementById('proactiveStatus').textContent = data.message || 'Request failed';
        document.getElementById('proactiveStatus').style.color = '#e74c3c';
        return;
      }
      await loadProactiveStatus();
    } catch(e) {
      document.getElementById('proactiveStatus').textContent = 'Request failed';
    }
  }

  async function saveProactiveConfig() {
    const fields = {
      proactive_quiet_hours_start: parseInt(document.getElementById('proactiveQuietStart').value) || 0,
      proactive_quiet_hours_end: parseInt(document.getElementById('proactiveQuietEnd').value) || 7,
      proactive_distraction_threshold: parseInt(document.getElementById('proactiveDistractionThreshold').value) || 20,
      proactive_checkin_interval: parseInt(document.getElementById('proactiveCheckinInterval').value) || 120,
    };
    for (const [k, v] of Object.entries(fields)) {
      await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[k]: v})
      });
    }
  }
```

- [ ] **Step 11: Run all tests**

```bash
pytest tests/test_supervisor.py tests/test_proactive.py tests/test_proactive_api.py -v
```

Expected: all PASS

- [ ] **Step 12: Run full suite**

```bash
pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 13: Commit**

```bash
git add core/main.py core/supervisor.py dashboard/static/index.html tests/test_supervisor.py
git commit -m "feat(proactive): wire lifespan, supervisor routes, and dashboard UI"
```
