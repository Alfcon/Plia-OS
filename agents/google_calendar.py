from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TOKEN_FILENAME = "gcal_token.json"


def _token_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / _TOKEN_FILENAME


def get_credentials():
    """Return valid Credentials or None if not authorized / not installed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    path = _token_path()
    if not path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path), _SCOPES)
    except Exception:
        logger.exception("Failed to load Google Calendar token from %s", path)
        return None
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        except Exception:
            logger.exception("Failed to refresh Google Calendar token")
            return None
    return creds if creds.valid else None


def build_auth_url(credentials_file: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(credentials_file: str, redirect_uri: str, code: str) -> None:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    _token_path().write_text(flow.credentials.to_json())
    logger.info("Google Calendar token saved to %s", _token_path())


def list_events(calendar_id: str = "primary", max_results: int = 20) -> list[dict]:
    creds = get_credentials()
    if creds is None:
        return []
    try:
        from googleapiclient.discovery import build
        from datetime import datetime, timezone
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc).isoformat()
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        items = result.get("items", [])
        events = []
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "uid": item.get("id", ""),
                "title": item.get("summary", ""),
                "dtstart": start.get("dateTime") or start.get("date", ""),
                "dtend": end.get("dateTime") or end.get("date", ""),
                "source": "google",
            })
        return events
    except Exception:
        logger.exception("Failed to list Google Calendar events")
        return []


def create_event(title: str, dtstart: str, dtend: str, calendar_id: str = "primary") -> str:
    creds = get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar not authorized")
    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    event_body = {
        "summary": title,
        "start": {"dateTime": dtstart, "timeZone": "UTC"},
        "end": {"dateTime": dtend, "timeZone": "UTC"},
    }
    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return created.get("id", "")


def delete_event(uid: str, calendar_id: str = "primary") -> None:
    creds = get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar not authorized")
    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    service.events().delete(calendarId=calendar_id, eventId=uid).execute()


def is_connected() -> bool:
    return get_credentials() is not None
