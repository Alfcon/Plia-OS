import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from voice.pipeline import VoicePipeline


def _make_pipeline(wake_detects_on=0):
    """
    Returns a VoicePipeline with all heavy services mocked.
    wake_detects_on: which call index to the wake detector returns True.
    """
    call_count = {"n": 0}

    def fake_detect(chunk):
        result = call_count["n"] == wake_detects_on
        call_count["n"] += 1
        return result

    mock_wake = MagicMock()
    mock_wake.detect.side_effect = fake_detect

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "turn the lights on"

    mock_tts = MagicMock()
    mock_tts.synthesise.return_value = np.zeros(24000, dtype=np.float32)

    pipeline = VoicePipeline()
    pipeline._wake = mock_wake
    pipeline._stt = mock_stt
    pipeline._tts = mock_tts
    return pipeline


async def test_pipeline_emits_status_events():
    from core import events

    emitted = []
    events.subscribe(lambda p: emitted.append(p))

    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._conversation = [{"role": "system", "content": "You are Plia."}]

    silence = np.zeros(1280, dtype=np.float32)
    speech = np.ones(1280, dtype=np.float32) * 0.1

    # Simulate: wake chunk → 5 speech chunks → 25 silence chunks
    chunks = [np.ones(1280, dtype=np.float32) * 0.9]  # triggers wake
    chunks += [speech] * 5
    chunks += [silence] * 25  # ends speech

    audio_q: asyncio.Queue = asyncio.Queue()
    for c in chunks:
        await audio_q.put(c)

    with patch("voice.pipeline.run_turn", new=AsyncMock(
        return_value=("Lights on!", [])
    )), patch("voice.pipeline.sd") as mock_sd:
        mock_sd.play = MagicMock()
        await pipeline._process_loop(audio_q, max_iterations=1)

    types = [e["type"] for e in emitted]
    assert "wake" in types
    assert "status" in types


async def test_empty_transcription_resets_to_armed():
    from core import events

    emitted = []
    events.subscribe(lambda p: emitted.append(p))

    silence = np.zeros(1280, dtype=np.float32)
    speech = np.ones(1280, dtype=np.float32) * 0.1

    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._stt.transcribe.return_value = ""  # blank transcription
    pipeline._conversation = [{"role": "system", "content": "sys"}]

    chunks = [np.ones(1280, dtype=np.float32) * 0.9]
    chunks += [speech] * 3
    chunks += [silence] * 25

    audio_q: asyncio.Queue = asyncio.Queue()
    for c in chunks:
        await audio_q.put(c)

    with patch("voice.pipeline.run_turn", new=AsyncMock()) as mock_run, \
         patch("voice.pipeline.sd"):
        await pipeline._process_loop(audio_q, max_iterations=1)
        mock_run.assert_not_called()

    statuses = [e["state"] for e in emitted if e["type"] == "status"]
    assert statuses[-1] == "armed"


@pytest.mark.asyncio
async def test_studio_pause_mode_skips_wake_word():
    """studio_pipeline_mode='pause' + heavy model active → wake detector never called."""
    from core.config import update_config

    update_config(studio_pipeline_mode="pause")

    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._conversation = [{"role": "system", "content": "sys"}]

    audio_q: asyncio.Queue = asyncio.Queue()
    audio_q.put_nowait(np.zeros(1280, dtype=np.int16))

    mock_broker = MagicMock()
    mock_broker.status.return_value = {"studio_mode": True}

    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        await pipeline._process_loop(audio_q, max_iterations=1)

    pipeline._wake.detect.assert_not_called()


@pytest.mark.asyncio
async def test_studio_pause_mode_cpu_stt_does_not_skip():
    """studio_pipeline_mode='cpu_stt' (default) does not skip wake word even with heavy model."""
    from core.config import update_config

    update_config(studio_pipeline_mode="cpu_stt")

    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._conversation = [{"role": "system", "content": "sys"}]

    speech = np.ones(1280, dtype=np.float32) * 0.1
    silence = np.zeros(1280, dtype=np.float32)
    chunks = [np.ones(1280, dtype=np.int16) * 8000]  # triggers wake (detect returns True on call 0)
    chunks += [speech.astype(np.int16)] * 3
    chunks += [(silence * 0).astype(np.int16)] * 25

    audio_q: asyncio.Queue = asyncio.Queue()
    for c in chunks:
        await audio_q.put(c)

    mock_broker = MagicMock()
    mock_broker.status.return_value = {"studio_mode": True}

    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker), \
         patch("voice.pipeline.run_turn", new=AsyncMock(return_value=("ok", []))), \
         patch("voice.pipeline.sd"):
        await pipeline._process_loop(audio_q, max_iterations=1)

    pipeline._wake.detect.assert_called()


@pytest.mark.asyncio
async def test_on_event_speak_queues_message():
    pipeline = VoicePipeline()
    await pipeline._on_event({"type": "speak", "message": "Hello world"})
    assert not pipeline._announcement_queue.empty()
    assert pipeline._announcement_queue.get_nowait() == "Hello world"


@pytest.mark.asyncio
async def test_on_event_speak_empty_message_ignored():
    pipeline = VoicePipeline()
    await pipeline._on_event({"type": "speak", "message": ""})
    assert pipeline._announcement_queue.empty()


@pytest.mark.asyncio
async def test_on_event_speak_queue_full_does_not_raise():
    pipeline = VoicePipeline()
    for _ in range(50):  # maxsize=50
        pipeline._announcement_queue.put_nowait("x")
    await pipeline._on_event({"type": "speak", "message": "overflow"})
    # No exception raised
