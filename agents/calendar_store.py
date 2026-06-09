from __future__ import annotations
import logging
import os
import uuid
from datetime import datetime, timedelta

from icalendar import Calendar, Event

logger = logging.getLogger(__name__)


class CalendarStore:
    def __init__(self, ics_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(ics_path)), exist_ok=True)
        self._path = ics_path
        if not os.path.exists(ics_path):
            self._write(self._blank_calendar())

    def _blank_calendar(self) -> Calendar:
        cal = Calendar()
        cal.add("prodid", "-//Plia-OS//Calendar//EN")
        cal.add("version", "2.0")
        return cal

    def _read(self) -> Calendar:
        with open(self._path, "rb") as f:
            return Calendar.from_ical(f.read())

    def _write(self, cal: Calendar) -> None:
        with open(self._path, "wb") as f:
            f.write(cal.to_ical())

    def add_event(
        self,
        title: str,
        date_str: str,
        time_str: str = "09:00",
        duration_min: int = 60,
    ) -> str:
        cal = self._read()
        event = Event()
        uid = str(uuid.uuid4())
        event.add("uid", uid)
        event.add("summary", title)
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValueError(f"Invalid date/time: '{date_str} {time_str}'") from exc
        event.add("dtstart", dt)
        event.add("dtend", dt + timedelta(minutes=duration_min))
        event.add("dtstamp", datetime.utcnow())
        cal.add_component(event)
        self._write(cal)
        logger.info("Added event '%s' uid=%s", title, uid[:8])
        return uid

    def list_events(self) -> list[str]:
        cal = self._read()
        results = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", ""))
            uid = str(component.get("uid", ""))
            dtstart = component.get("dtstart")
            if dtstart:
                dt = dtstart.dt
                dt_str = (
                    dt.strftime("%Y-%m-%d %H:%M")
                    if isinstance(dt, datetime)
                    else str(dt)
                )
            else:
                dt_str = "unknown"
            results.append(f"{dt_str}: {summary} (uid: {uid[:8]})")
        return sorted(results) if results else ["No events found"]

    def delete_event(self, uid: str) -> bool:
        cal = self._read()
        new_cal = self._blank_calendar()
        found = False
        for component in cal.walk():
            if component.name == "VEVENT":
                if str(component.get("uid", "")) == uid:
                    found = True
                else:
                    new_cal.add_component(component)
        if found:
            self._write(new_cal)
            logger.info("Deleted event uid=%s", uid[:8])
        return found


_store: CalendarStore | None = None


def get_calendar_store() -> CalendarStore:
    global _store
    if _store is None:
        from core.config import get_config
        config = get_config()
        ics_path = os.path.join(config.memory_dir, "calendar.ics")
        _store = CalendarStore(ics_path)
    return _store


def reset_calendar_store() -> None:
    """Test helper — clears singleton so each test gets a fresh store."""
    global _store
    _store = None
