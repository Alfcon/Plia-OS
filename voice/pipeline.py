import asyncio
import logging
import numpy as np
from core.agent import run_turn
from core.config import get_config
from core import events
from voice.wake import WakeWordDetector
from voice.stt import STTService
from voice.tts import TTSService

try:
    import sounddevice as sd
except ImportError:
    sd = None  # allows import in test environments without audio hardware

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_BLOCK_SIZE = 1280  # ~80ms per chunk at 16kHz
_ENERGY_FLOOR = 0.01  # RMS below this = silence


class VoicePipeline:
    """
    State machine: armed → listening → processing → speaking → armed.
    Runs as an asyncio background task; never crashes — always returns to armed.
    """

    def __init__(self) -> None:
        self._wake = WakeWordDetector()
        self._stt = STTService()
        self._tts = TTSService()
        self._running = False
        self._conversation: list[dict] = []

    def load(self) -> None:
        self._wake.load()
        self._stt.load()
        self._tts.load()
        config = get_config()
        self._conversation = [{"role": "system", "content": config.system_prompt}]

    async def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        audio_q: asyncio.Queue[np.ndarray] = asyncio.Queue()

        def _cb(indata, frames, time, status):
            loop.call_soon_threadsafe(audio_q.put_nowait, indata[:, 0].copy())

        await events.emit("status", {"state": "armed"})
        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=_BLOCK_SIZE,
            callback=_cb,
        ):
            while self._running:
                try:
                    await self._process_loop(audio_q)
                except Exception:
                    logger.exception("Pipeline error; resetting to armed")
                    await events.emit("status", {"state": "armed"})

    async def stop(self) -> None:
        self._running = False

    async def _process_loop(
        self,
        audio_q: asyncio.Queue,
        max_iterations: int | None = None,
    ) -> None:
        """One full armed→speaking cycle. max_iterations limits loops for tests."""
        config = get_config()
        iterations = 0

        while max_iterations is None or iterations < max_iterations:
            iterations += 1

            # --- Phase 1: wait for wake word ---
            await events.emit("status", {"state": "armed"})
            while True:
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if max_iterations is not None:
                        return
                    continue
                chunk_int16 = (chunk * 32768).astype(np.int16)
                if self._wake.detect(chunk_int16):
                    self._wake.reset()
                    await events.emit("wake", {"detected": True})
                    break

            # --- Phase 2: collect speech until silence ---
            await events.emit("status", {"state": "listening"})
            speech_chunks: list[np.ndarray] = []
            silence_count = 0

            while True:
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=config.silence_timeout_seconds)
                except asyncio.TimeoutError:
                    break
                speech_chunks.append(chunk)
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if rms < _ENERGY_FLOOR:
                    silence_count += 1
                    if silence_count >= config.silence_chunks_threshold:
                        break
                else:
                    silence_count = 0

            if not speech_chunks:
                continue

            # --- Phase 3: transcribe ---
            await events.emit("status", {"state": "processing"})
            audio = np.concatenate(speech_chunks)
            text = self._stt.transcribe(audio)
            if not text:
                await events.emit("status", {"state": "armed"})
                continue

            await events.emit("transcript", {"role": "user", "text": text})
            self._conversation.append({"role": "user", "content": text})

            # --- Phase 4: LLM + tool calls ---
            try:
                response, self._conversation = await run_turn(self._conversation)
            except Exception as exc:
                logger.error("Agent error: %s", exc)
                response = "I encountered an error. Please try again."

            await events.emit("transcript", {"role": "assistant", "text": response})

            # --- Phase 5: speak ---
            await events.emit("status", {"state": "speaking"})
            try:
                audio_out = self._tts.synthesise(response)
                sd.play(audio_out, samplerate=24000, blocking=True)
            except Exception:
                logger.exception("TTS playback error")
                await events.emit("status", {"state": "armed"})
