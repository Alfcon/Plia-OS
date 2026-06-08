"""Hardware capability detection — determines which TTS engines fit on this system.

Uses PyTorch for GPU VRAM detection. If llmfit is installed, it is also available
for extended LLM/model queries via the `query_llmfit` helper.
"""
import logging
import subprocess
import json

logger = logging.getLogger(__name__)

# VRAM required (GB) for each TTS engine
ENGINE_VRAM_GB: dict[str, float] = {
    "kokoro": 0.4,
    "chatterbox": 2.0,
    "dramabox": 8.52,
}


def get_gpu_vram_gb() -> float:
    """Return total GPU VRAM in GB for the primary CUDA device, or 0 if none."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def get_gpu_name() -> str | None:
    """Return GPU device name, or None if not available."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).name
    except Exception:
        pass
    return None


def engine_fits(engine: str) -> bool:
    required = ENGINE_VRAM_GB.get(engine, 0.0)
    return get_gpu_vram_gb() >= required


def capabilities() -> dict:
    """Return per-engine fit status based on available GPU VRAM."""
    available = get_gpu_vram_gb()
    gpu_name = get_gpu_name()
    result: dict = {
        "_system": {
            "gpu_name": gpu_name,
            "gpu_vram_gb": round(available, 2),
        }
    }
    for engine, required_gb in ENGINE_VRAM_GB.items():
        fits = available >= required_gb
        result[engine] = {
            "fits": fits,
            "vram_required_gb": required_gb,
            "vram_available_gb": round(available, 2),
            "reason": (
                None if fits
                else f"Requires {required_gb:.2f} GB VRAM but only {available:.1f} GB available on {gpu_name or 'GPU'}"
            ),
        }
    return result


def query_llmfit(model_name: str | None = None) -> dict | None:
    """Run llmfit in CLI mode and return JSON output. Returns None if llmfit not installed.

    If model_name is given, searches for that model in llmfit's database.
    llmfit knows about LLM text models (Llama, Mistral, etc.) but not TTS engines —
    use capabilities() for TTS engine fit checks.
    """
    try:
        # llmfit --json flag emits JSON system + model info then exits
        args = ["llmfit", "--json"]
        if model_name:
            args += ["--search", model_name]
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except FileNotFoundError:
        logger.debug("llmfit not installed; skipping extended model query")
    except Exception:
        logger.debug("llmfit query failed", exc_info=True)
    return None


def check_custom_fit(model_name: str, vram_required_gb: float) -> dict:
    """Check if a custom model/app with known VRAM requirement fits this system."""
    available = get_gpu_vram_gb()
    fits = available >= vram_required_gb
    return {
        "model": model_name,
        "fits": fits,
        "vram_required_gb": vram_required_gb,
        "vram_available_gb": round(available, 2),
        "reason": (
            None if fits
            else f"{model_name} requires {vram_required_gb:.2f} GB VRAM but only {available:.1f} GB is available"
        ),
    }
