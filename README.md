# Plia-OS

A local AI voice assistant with a web dashboard and a multi-agent backend.

## How it works

1. **Wake word** — openwakeword listens for the wake phrase
2. **STT** — faster-whisper transcribes speech to text
3. **Agents** — a LangGraph supervisor routes the request to specialist agents
4. **TTS** — Kokoro, Chatterbox, or Dramabox speaks the response

The dashboard (FastAPI + browser UI) lets you monitor and configure everything at runtime.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with a model loaded (default: `llama3.2`)
- A microphone

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional extras:

```bash
pip install -e ".[playwright]"          # web scraping
pip install -e ".[fallback-openai]"     # OpenAI fallback LLM
pip install -e ".[fallback-anthropic]"  # Anthropic fallback LLM
pip install -e ".[dramabox]"            # Dramabox TTS engine
```

## Run

```bash
python -m core.main
```

Dashboard opens at `http://localhost:8000`. The voice pipeline starts automatically; the dashboard stays available even if the pipeline fails to load.

## Agents

| Agent | What it does |
|-------|-------------|
| memory | Remembers facts, history, and reminders (SQLite + ChromaDB) |
| web | Searches the web via DuckDuckGo, Google Custom Search, or Playwright |
| code | Runs Python snippets and shell commands in a sandboxed subprocess |
| calendar | Adds, lists, and deletes events in `~/.plia/calendar.ics` |
| home | Smart home stub (not yet implemented) |

## Configuration

All config lives in `core/config.py` as a `PliaConfig` dataclass. Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `ollama_model` | `llama3.2` | Model to use for inference |
| `tts_engine` | `kokoro` | TTS engine: `kokoro`, `chatterbox`, or `dramabox` |
| `stt_model_size` | `base` | Whisper model size |
| `web_search_default` | `ddg` | Default web search provider |
| `memory_dir` | `~/.plia` | Where memory DB and calendar ICS are stored |
| `fallback_provider` | _(empty)_ | Cloud fallback LLM: `openai` or `anthropic` |

Settings can be changed live from the dashboard without restarting.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

164 tests, all passing.
