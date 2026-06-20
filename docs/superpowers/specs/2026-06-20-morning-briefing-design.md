# Morning Briefing Design

**Date:** 2026-06-20  
**Status:** Approved

## Goal

Add a `morning_briefing()` tool that compiles weather, reminders, calendar events, and news into a single spoken + chat-displayed digest, triggered on demand by voice or text.

## Architecture

A single `@tool` function in `modules/briefing_tools.py`. No new agent node, no new loop. The existing `respond` agent calls it when the user asks for a briefing; the LLM wraps the result naturally; the normal TTS + WebSocket transcript flow handles delivery.

```
user: "morning briefing"
  → supervisor keyword route → respond agent
  → LLM calls morning_briefing()
  → tool gathers: weather + reminders + calendar + news
  → returns formatted string
  → LLM presents it
  → VoicePipeline speaks it + dashboard chat shows it
```

## Components

### `modules/briefing_tools.py`

One `@tool("Get the morning briefing...")` function: `morning_briefing() -> str`.

Gathers four sections synchronously:

| Section | Source | Filter |
|---------|--------|--------|
| Weather | Open-Meteo via `weather_tools` internals | Today's high/low/condition/UV |
| Reminders | `memory_store.list_pending()` | Due today (UTC date match) |
| Calendar | `calendar_store.list_events()` + Google Calendar sync if configured | Date == today |
| News | `news_tools.fetch_news(topic, max_items=5)` | `briefing_news_topic` config field |

Each section degrades gracefully: if a source fails or returns empty, that section is omitted with no error surfaced to the user. Weather location not set → weather section skipped. No reminders today → reminders section omitted.

Output format (plain text, TTS-friendly — no markdown):

```
Good morning. Here's your briefing for [weekday, date].

Weather: [city] — [condition], high [X]°C, low [Y]°C. UV index [label].

Reminders today: [message 1]. [message 2].

Calendar: [event title] at [time]. [event 2 title] at [time].

News — [topic]: [headline 1]. [headline 2]. [headline 3].
```

Sections with no data are omitted entirely. If all four fail, returns a short fallback message.

### Config (`core/config.py`)

One new field on `PliaConfig`:

```python
briefing_news_topic: str = "world news"
```

No `_LITERAL_CONSTRAINTS` entry needed (free-form string).

### Keyword Routes (`core/supervisor.py`)

Added to `_KEYWORD_ROUTES["respond"]`:

```python
"morning briefing", "daily briefing", "today's briefing",
"good morning", "what's today", "give me a briefing",
```

### Settings UI (`dashboard/static/index.html`)

New "Briefing" row in Settings → System pane:

- Label: "News topic"
- Text input bound to `briefing_news_topic`
- Apply button POSTs to `POST /api/config`

Populated on settings load via the existing `GET /api/config` fetch block.

## Data Flow Detail

```
morning_briefing()
  ├── weather: _resolve_location(cfg.weather_location) → Open-Meteo HTTP → format 1 line
  ├── reminders: get_memory_store().list_pending() → filter fire_at.date() == today → format list
  ├── calendar: get_calendar_store().list_events_json() → filter date == today → format list
  └── news: fetch_news(cfg.briefing_news_topic, max_items=5) → extract headlines → format list
```

All four run sequentially (no async needed — tool is called from sync context via `asyncio.to_thread`). Each section is wrapped in its own try/except; failure of one does not abort others.

## Testing (`tests/test_briefing_tools.py`)

| Test | What it checks |
|------|---------------|
| `test_briefing_all_sections` | All four sections present when all sources return data |
| `test_briefing_no_reminders` | Reminder section omitted when list empty |
| `test_briefing_no_calendar` | Calendar section omitted when no events today |
| `test_briefing_weather_error` | Weather section omitted when location not set or HTTP fails |
| `test_briefing_news_uses_config_topic` | `fetch_news` called with `briefing_news_topic` value |
| `test_briefing_all_fail` | Returns non-empty fallback string when all sources fail |
| `test_briefing_registered_as_tool` | `morning_briefing` present in tool registry |

## Out of Scope

- Cron/scheduled auto-delivery (user can add a cron job manually if desired)
- Per-section enable/disable toggles (all sections always attempted; empty ones auto-hidden)
- News source selection beyond topic string
- Personalisation / historical trend comparison
