import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path(
    os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
)


@dataclass
class PliaConfig:
    # LLM
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    system_prompt: str = "You are Plia, a helpful local AI assistant. Be concise."

    # Wake word
    wake_word_model: str = "hey_jarvis"  # closest built-in; replace with custom trained model
    wake_word_threshold: float = 0.5

    # STT
    stt_model_size: str = "base"  # tiny | base | small | medium | large
    stt_language: str = "en"

    # TTS
    tts_engine: Literal["kokoro", "chatterbox", "dramabox"] = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    chatterbox_reference_audio: str | None = None
    chatterbox_exaggeration: float = 0.5
    dramabox_voice_ref: str | None = None
    dramabox_cfg_scale: float = 2.5
    dramabox_stg_scale: float = 1.5
    dramabox_seed: int = 42
    dramabox_duration_multiplier: float = 1.1

    # Studio mode
    studio_pipeline_mode: Literal["cpu_stt", "pause"] = "cpu_stt"

    # Chatterbox sampling
    chatterbox_seed: int | None = None
    chatterbox_temperature: float = 0.8
    chatterbox_cfg_weight: float = 0.5

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Pipeline
    silence_timeout_seconds: float = 8.0
    silence_chunks_threshold: int = 10  # consecutive ~80ms chunks below energy floor

    # Multiagent LLM fallback
    fallback_provider: str = ""
    fallback_model: str = ""
    fallback_api_key: str = ""

    # Web agent
    web_search_default: str = "ddg"
    web_search_max_results: int = 5
    google_search_api_key: str = ""
    google_search_cx: str = ""

    # Memory agent
    memory_dir: str = field(default_factory=lambda: os.path.expanduser("~/.plia"))

    # Home automation (Home Assistant)
    hass_url: str = ""
    hass_token: str = ""

    # Google Calendar
    gcal_credentials_file: str = ""  # path to OAuth 2.0 client_secret.json from Google Cloud Console
    gcal_calendar_id: str = "primary"


_LITERAL_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "tts_engine": ("kokoro", "chatterbox", "dramabox"),
    "studio_pipeline_mode": ("cpu_stt", "pause"),
}


def _load_persisted(config: PliaConfig) -> None:
    if not _CONFIG_FILE.exists():
        return
    try:
        data = json.loads(_CONFIG_FILE.read_text())
        for key, value in data.items():
            if not hasattr(config, key):
                continue
            allowed = _LITERAL_CONSTRAINTS.get(key)
            if allowed is not None and value not in allowed:
                logger.warning("Ignoring invalid persisted value %r for %r; allowed: %s", value, key, allowed)
                continue
            current = getattr(config, key)
            if value is None and current is not None:
                logger.warning("Ignoring null in persisted config for %r; keeping default", key)
                continue
            if current is not None and value is not None:
                target = type(current)
                if not isinstance(value, target):
                    try:
                        value = target(value)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Cannot coerce %r for %r to %s; skipping",
                            value, key, target.__name__,
                        )
                        continue
            setattr(config, key, value)
    except Exception as exc:
        logger.warning("Could not load persisted config from %s: %s", _CONFIG_FILE, exc)


def _save_persisted(config: PliaConfig) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(dataclasses.asdict(config), indent=2))
    except Exception as exc:
        logger.warning("Could not save config to %s: %s", _CONFIG_FILE, exc)


_config = PliaConfig()
_load_persisted(_config)


def get_config() -> PliaConfig:
    return _config


def update_config(**kwargs) -> PliaConfig:
    for key, value in kwargs.items():
        if not hasattr(_config, key):
            raise ValueError(f"Unknown config key: {key!r}")
        if key in _LITERAL_CONSTRAINTS and value not in _LITERAL_CONSTRAINTS[key]:
            raise ValueError(
                f"Invalid value {value!r} for {key!r}; "
                f"allowed: {_LITERAL_CONSTRAINTS[key]}"
            )
        setattr(_config, key, value)
    _save_persisted(_config)
    return _config


def reset_config() -> None:
    """For testing only."""
    global _config
    _config = PliaConfig()
