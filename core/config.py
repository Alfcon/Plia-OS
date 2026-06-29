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
    system_prompt_backup: str = ""

    # Wake word
    wake_word_model: str = "hey_jarvis"  # closest built-in; replace with custom trained model
    wake_word_threshold: float = 0.5

    # STT
    stt_model_size: str = "base"  # tiny | base | small | medium | large
    stt_language: str = "en"  # set to "" or "auto" to enable per-chunk language detection

    # TTS
    tts_engine: Literal["kokoro", "chatterbox", "dramabox"] = "kokoro"
    tts_max_words: int = 0  # 0 = no truncation; >0 = truncate voice output at sentence boundary
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

    # AirLLM — large model inference via layer sharding (empty = disabled)
    airllm_model: str = ""
    airllm_compression: str = "4bit"  # 4bit | 8bit | none

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

    # Module manager
    disabled_modules: list = field(default_factory=list)

    # Permissions — maps tool name → "admin" | "user"
    tool_permissions: dict = field(default_factory=dict)

    # Notifications
    desktop_notifications: bool = True

    # Tor VPN
    tor_enabled: bool = False

    # Observer — user activity monitoring
    observer_enabled: bool = False
    observer_screen_interval: int = 30
    observer_profile_interval: int = 300
    observer_retention_hours: int = 24

    # Proactive assistant — observer-triggered suggestions
    proactive_enabled: bool = False
    proactive_check_interval: int = 60          # seconds between trigger checks
    proactive_distraction_threshold: int = 20   # minutes before distraction trigger
    proactive_checkin_interval: int = 120       # minutes between scheduled check-ins
    proactive_quiet_hours_start: int = 0        # hour 0-23, voice silenced from
    proactive_quiet_hours_end: int = 7          # hour 0-23, voice silenced until

    # Weather
    weather_location: str = ""

    # Briefing
    briefing_news_topic: str = "breaking news"
    briefing_cron_enabled: bool = False
    briefing_cron_time: str = "07:00"
    briefing_include_weather: bool = True
    briefing_include_reminders: bool = True
    briefing_include_calendar: bool = True
    briefing_include_email: bool = True
    briefing_include_news: bool = True

    # Tool guard — tools in this list require user approval before execution
    tool_guard_list: list = field(default_factory=list)

    # Audio devices (None = system default)
    audio_input_device: int | None = None
    audio_output_device: int | None = None

    # System resource alerts
    alerts_enabled: bool = False
    cpu_alert_threshold: int = 90
    ram_alert_threshold: int = 90
    gpu_alert_threshold: int = 90
    llm_cache_enabled: bool = False
    llm_cache_max: int = 100


_LITERAL_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "tts_engine": ("kokoro", "chatterbox", "dramabox"),
    "studio_pipeline_mode": ("cpu_stt", "pause"),
    "stt_model_size": ("tiny", "base", "small", "medium", "large"),
    "airllm_compression": ("4bit", "8bit", "none"),
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
    if "airllm_model" in kwargs and kwargs["airllm_model"] != _config.airllm_model:
        try:
            from agents.airllm_backend import unload
            unload()
        except Exception:
            pass
    # Auto-backup system_prompt before loop so order of kwargs doesn't matter (V9 fix)
    if "system_prompt" in kwargs and kwargs["system_prompt"] != _config.system_prompt:
        _config.system_prompt_backup = _config.system_prompt
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


def restore_system_prompt() -> str:
    """One-shot undo: restore system_prompt from backup and clear the backup slot.

    Returns the restored prompt, or "" if no backup exists.
    """
    if not _config.system_prompt_backup:
        return ""
    _config.system_prompt = _config.system_prompt_backup
    _config.system_prompt_backup = ""
    _save_persisted(_config)
    return _config.system_prompt


def reset_system_prompt_to_default() -> str:
    """Reset system_prompt to factory default without touching system_prompt_backup."""
    default: str = PliaConfig.__dataclass_fields__["system_prompt"].default
    if _config.system_prompt != default:
        _config.system_prompt = default
        _save_persisted(_config)
    return _config.system_prompt


def reset_config() -> None:
    """For testing only."""
    global _config
    _config = PliaConfig()
