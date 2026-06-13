import asyncio
import logging
import time
import numpy as np
from core.supervisor import run_turn
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
_ENERGY_FLOOR = 0.03  # RMS below this = silence (normalised to [-1,1])
_INT16_MAX = 32768.0  # used to normalise int16 → float for RMS and STT
_HISTORY_PRELOAD = 20  # number of recent messages to preload on startup


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
        self._wake_muted_until: float = 0.0  # epoch time; wake ignored before this
        self._announcement_queue: asyncio.Queue[str] = asyncio.Queue()

    def load(self) -> None:
        self._wake.load()
        self._stt.load()
        self._tts.load()
        config = get_config()
        from agents.chat_history import get_recent
        history = get_recent(_HISTORY_PRELOAD)
        self._conversation = [{"role": "system", "content": config.system_prompt}] + [
            {"role": m["role"], "content": m["content"]}
            for m in history
            if m["role"] != "system"
        ]
        if self._on_event not in events._subscribers:
            events.subscribe(self._on_event)

    async def _on_event(self, payload: dict) -> None:
        if payload.get("type") == "clear_history":
            config = get_config()
            self._conversation = [{"role": "system", "content": config.system_prompt}]
            logger.info("Pipeline conversation history cleared")
        elif payload.get("type") == "reminder_fired":
            message = payload.get("message", "Reminder")
            self._announcement_queue.put_nowait(f"Reminder: {message}")
            logger.info("Queued reminder announcement: %s", message)

    async def _speak_announcement(self, message: str) -> None:
        logger.info("Announcing: %s", message)
        try:
            await events.emit("transcript", {"role": "assistant", "text": message})
            audio_out = self._tts.synthesise(message)
            self._wake_muted_until = time.monotonic() + len(audio_out) / 24000.0 + 4.0
            sd.play(audio_out, samplerate=24000, blocking=True)
        except Exception:
            logger.exception("Reminder announcement failed")

    async def start(self) -> None:
        self._running = True
        loop = asyncio.get_event_loop()
        audio_q: asyncio.Queue[np.ndarray] = asyncio.Queue()

        def _cb(indata, frames, time, status):
            # Capture as int16 to avoid PipeWire float32 normalisation issues
            loop.call_soon_threadsafe(audio_q.put_nowait, indata[:, 0].copy())

        await events.emit("status", {"state": "armed"})
        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
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

            # --- Phase 0: speak any queued reminder announcements ---
            while not self._announcement_queue.empty():
                try:
                    message = self._announcement_queue.get_nowait()
                    await self._speak_announcement(message)
                except asyncio.QueueEmpty:
                    break

            # --- Phase 1: wait for wake word ---
            await events.emit("status", {"state": "armed"})
            remaining = self._wake_muted_until - time.monotonic()
            if remaining > 0:
                logger.info("Echo mute: sleeping %.2fs to clear hardware echo", remaining)
                while not audio_q.empty():
                    audio_q.get_nowait()
                await asyncio.sleep(remaining)
                while not audio_q.empty():
                    audio_q.get_nowait()
                self._wake.reset()
            while True:
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if max_iterations is not None:
                        return
                    continue
                if self._wake.detect(chunk):  # chunk is already int16
                    self._wake.reset()
                    logger.info("Wake word detected")
                    await events.emit("wake", {"detected": True})
                    break

            # --- Phase 2: collect speech until silence ---
            await events.emit("status", {"state": "listening"})
            logger.info("Listening for speech...")
            speech_chunks: list[np.ndarray] = []
            silence_count = 0
            speech_detected = False
            deadline = asyncio.get_event_loop().time() + config.silence_timeout_seconds

            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(audio_q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                speech_chunks.append(chunk)
                rms = float(np.sqrt(np.mean((chunk / _INT16_MAX) ** 2)))
                if rms >= _ENERGY_FLOOR:
                    speech_detected = True
                    silence_count = 0
                elif speech_detected:
                    silence_count += 1
                    if silence_count >= config.silence_chunks_threshold:
                        logger.info("Silence detected — collected %d chunks", len(speech_chunks))
                        break
            else:
                logger.info("Listening timed out after %.0fs", config.silence_timeout_seconds)

            if not speech_chunks:
                logger.info("No speech captured, returning to armed")
                continue

            # --- Phase 3: transcribe ---
            await events.emit("status", {"state": "processing"})
            audio_int16 = np.concatenate(speech_chunks)
            audio = audio_int16.astype(np.float32) / _INT16_MAX
            logger.info("Transcribing %.1f seconds of audio (rms=%.3f)...",
                        len(audio) / _SAMPLE_RATE,
                        float(np.sqrt(np.mean(audio ** 2))))
            text = self._stt.transcribe(audio)
            logger.info("Transcript: %r", text)
            if not text:
                logger.info("Empty transcript, returning to armed")
                await events.emit("status", {"state": "armed"})
                continue

            await events.emit("transcript", {"role": "user", "text": text})
            self._conversation.append({"role": "user", "content": text})

            # --- Phase 4: LLM + tool calls ---
            logger.info("Calling LLM...")
            try:
                response, self._conversation = await run_turn(self._conversation)
            except Exception as exc:
                logger.error("Agent error: %s", exc)
                response = "I encountered an error. Please try again."
            logger.info("LLM response: %r", response)

            await events.emit("transcript", {"role": "assistant", "text": response})

            # --- Phase 5: speak ---
            await events.emit("status", {"state": "speaking"})
            logger.info("Synthesising speech...")
            try:
                audio_out = self._tts.synthesise(response)
                logger.info("Playing audio (%d samples)...", len(audio_out))
                # Mute before playback: audio duration + 4s tail covers hardware buffer echo
                self._wake_muted_until = time.monotonic() + len(audio_out) / 24000.0 + 4.0
                while not audio_q.empty():
                    audio_q.get_nowait()
                sd.play(audio_out, samplerate=24000, blocking=True)
                logger.info("Playback complete")
                while not audio_q.empty():
                    audio_q.get_nowait()
                self._wake.reset()
            except Exception:
                logger.exception("TTS playback error")
                await events.emit("status", {"state": "armed"})
