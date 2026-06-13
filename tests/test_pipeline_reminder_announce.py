import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from voice.pipeline import VoicePipeline
from core import events


def _pipeline():
    p = VoicePipeline()
    p._wake = MagicMock()
    p._stt = MagicMock()
    p._tts = MagicMock()
    p._tts.synthesise.return_value = np.zeros(24000, dtype=np.float32)
    return p


@pytest.fixture(autouse=True)
def clear_events():
    events.clear_subscribers()
    yield
    events.clear_subscribers()


async def test_reminder_fired_enqueues_announcement():
    p = _pipeline()
    await events.emit("reminder_fired", {"id": 1, "message": "Take medication"})
    assert p._announcement_queue.empty()  # not subscribed yet — confirm no magic

    events.subscribe(p._on_event)
    await events.emit("reminder_fired", {"id": 2, "message": "Call doctor"})
    assert not p._announcement_queue.empty()
    msg = p._announcement_queue.get_nowait()
    assert "Call doctor" in msg


async def test_reminder_fired_prefixes_reminder():
    p = _pipeline()
    events.subscribe(p._on_event)
    await events.emit("reminder_fired", {"id": 1, "message": "Stand up"})
    msg = p._announcement_queue.get_nowait()
    assert msg.startswith("Reminder:")
    assert "Stand up" in msg


async def test_speak_announcement_calls_tts_and_emits_transcript():
    p = _pipeline()
    transcripts = []
    events.subscribe(lambda payload: transcripts.append(payload) if payload.get("type") == "transcript" else None)

    with patch("voice.pipeline.sd") as mock_sd:
        mock_sd.play = MagicMock()
        await p._speak_announcement("Reminder: Take medication")

    p._tts.synthesise.assert_called_once_with("Reminder: Take medication")
    mock_sd.play.assert_called_once()
    assert any("Take medication" in t.get("text", "") for t in transcripts)


async def test_speak_announcement_sets_wake_mute():
    p = _pipeline()
    with patch("voice.pipeline.sd"):
        await p._speak_announcement("Reminder: Test")
    assert p._wake_muted_until > 0


async def test_speak_announcement_tts_error_does_not_raise():
    p = _pipeline()
    p._tts.synthesise.side_effect = RuntimeError("TTS offline")
    with patch("voice.pipeline.sd"):
        await p._speak_announcement("Reminder: Test")  # must not raise


async def test_process_loop_drains_announcement_queue():
    p = _pipeline()
    p._conversation = [{"role": "system", "content": "You are Plia."}]

    await p._announcement_queue.put("Reminder: Walk the dog")

    spoken = []

    async def fake_speak(msg):
        spoken.append(msg)

    p._speak_announcement = fake_speak

    audio_q: asyncio.Queue = asyncio.Queue()
    # Feed one timeout worth of silence so the loop exits after Phase 0
    with patch("voice.pipeline.sd"):
        try:
            await asyncio.wait_for(
                p._process_loop(audio_q, max_iterations=1),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            pass

    assert "Reminder: Walk the dog" in spoken
