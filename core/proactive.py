from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from core.config import get_config
from core import events

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
        cfg = get_config()
        if cfg.fallback_provider:
            return

        self._check_interval = cfg.proactive_check_interval
        self._distraction_threshold = cfg.proactive_distraction_threshold
        self._checkin_interval = cfg.proactive_checkin_interval
        self._quiet_start = cfg.proactive_quiet_hours_start
        self._quiet_end = cfg.proactive_quiet_hours_end

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

        # anomaly: current (app, hour) not seen in retention window
        if app:
            cfg = get_config()
            history_days = max(1, cfg.observer_retention_hours // 24)
            history = await asyncio.to_thread(store.get_app_hour_history, history_days)
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
        cfg = get_config()
        self._quiet_start = cfg.proactive_quiet_hours_start
        self._quiet_end = cfg.proactive_quiet_hours_end
        now_hour = datetime.now().hour
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
