import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent


class DramaboxTTS:
    def __init__(self) -> None:
        self._server = None

    @staticmethod
    def _setup_paths() -> None:
        for p in [str(_HERE / "ltx2"), str(_HERE / "src")]:
            if p not in sys.path:
                sys.path.insert(0, p)

    def load(self) -> None:
        self._setup_paths()
        from inference_server import TTSServer
        from model_downloader import get_model_path, get_gemma_path

        transformer = get_model_path("transformer")
        audio_components = get_model_path("audio_components")
        gemma_root = get_gemma_path()
        self._server = TTSServer(
            checkpoint=transformer,
            full_checkpoint=audio_components,
            gemma_root=gemma_root,
            device="cuda",
            dtype="bf16",
            compile_model=False,
            bnb_4bit=True,
        )

    def synthesise(self, text: str):
        from core.config import get_config
        config = get_config()
        waveform, sr = self._server.generate(
            prompt=text,
            voice_ref=config.dramabox_voice_ref,
            cfg_scale=config.dramabox_cfg_scale,
            stg_scale=config.dramabox_stg_scale,
            seed=config.dramabox_seed,
            duration_multiplier=config.dramabox_duration_multiplier,
        )
        return waveform.cpu().float(), sr

    def generate_to_file(self, prompt: str, dest: str,
                         progress_callback=None) -> str:
        from core.config import get_config
        config = get_config()
        self._server.generate_to_file(
            prompt=prompt,
            output=dest,
            voice_ref=config.dramabox_voice_ref,
            cfg_scale=config.dramabox_cfg_scale,
            stg_scale=config.dramabox_stg_scale,
            seed=config.dramabox_seed,
            duration_multiplier=config.dramabox_duration_multiplier,
            watermark=True,
            progress_callback=progress_callback,
        )
        return dest
