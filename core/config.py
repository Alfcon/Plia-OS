from dataclasses import dataclass
from typing import Literal


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
    tts_engine: Literal["kokoro", "chatterbox"] = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    chatterbox_reference_audio: str | None = None
    chatterbox_exaggeration: float = 0.5

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Pipeline
    silence_timeout_seconds: float = 8.0
    silence_chunks_threshold: int = 10  # consecutive ~80ms chunks below energy floor


_config = PliaConfig()


def get_config() -> PliaConfig:
    return _config


def update_config(**kwargs) -> PliaConfig:
    for key, value in kwargs.items():
        if not hasattr(_config, key):
            raise ValueError(f"Unknown config key: {key!r}")
        setattr(_config, key, value)
    return _config


def reset_config() -> None:
    """For testing only."""
    global _config
    _config = PliaConfig()
