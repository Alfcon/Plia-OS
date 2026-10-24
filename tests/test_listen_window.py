"""The listen window must end on silence, not on a fixed deadline.

Regression: `deadline` was set once before the loop from silence_timeout_seconds
and never extended, so that field was a hard cap on the whole utterance despite
its name. At the user's persisted value of 2, "Hey Jarvis, Clear all Chat
Archive" was captured as exactly 2.000s and transcribed "Clear all chat".

Note on methodology: the tests using pre-queued chunks cannot exercise any
wall-clock deadline — Queue.get() resolves in microseconds, so the loop's
elapsed time never approaches silence_timeout_seconds or max_utterance_seconds.
They verify the chunk/silence logic only. The real-time-paced tests at the end
of this file are the ones that prove the truncation fix.
"""
import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, patch

from core.config import get_config, update_config
from tests.test_pipeline import _make_pipeline


def _set_timing(**kwargs):
    """Set timing fields directly, bypassing update_config's range validation.

    The paced tests use sub-range values (e.g. max_utterance_seconds=0.4)
    purely to keep wall-clock runtimes short; the loop math under test is
    identical. Range validation has its own tests in test_config_persist.py.
    """
    cfg = get_config()
    for k, v in kwargs.items():
        setattr(cfg, k, v)

_CHUNK = 1280  # samples; 80ms at 16kHz
# Pipeline RMS is computed as chunk / _INT16_MAX (chunks are raw int16-range
# audio in production), so fixtures must be int16-scale for the energy floor
# comparison to mean anything — 0.1 alone would round to ~0 after that
# division and be indistinguishable from silence.
_INT16_MAX = 32768.0
SPEECH = np.ones(_CHUNK, dtype=np.float32) * 0.1 * _INT16_MAX   # rms 0.1 > _ENERGY_FLOOR 0.03
SILENCE = np.zeros(_CHUNK, dtype=np.float32)
WAKE = np.ones(_CHUNK, dtype=np.float32) * 0.9 * _INT16_MAX     # amplitude irrelevant; wake detection is mocked


async def _run(chunks):
    """Drive one turn and return the audio handed to STT."""
    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._conversation = [{"role": "system", "content": "sys"}]
    q: asyncio.Queue = asyncio.Queue()
    for c in chunks:
        await q.put(c)
    with patch("voice.pipeline.run_turn", new=AsyncMock(return_value=("ok", []))), \
         patch("voice.pipeline.sd"):
        await pipeline._process_loop(q, max_iterations=1)
    assert pipeline._stt.transcribe.called, "STT was never called"
    return pipeline._stt.transcribe.call_args[0][0]


async def test_long_utterance_is_not_truncated():
    # 3s of continuous speech. Dies at 2.0s today.
    update_config(silence_timeout_seconds=0.8, max_utterance_seconds=15.0)
    audio = await _run([WAKE] + [SPEECH] * 38 + [SILENCE] * 15)
    seconds = len(audio) / 16000
    assert seconds > 3.0, f"utterance truncated to {seconds:.2f}s"


async def test_silence_ends_the_turn():
    # 10 silent chunks == 0.8s == silence_timeout_seconds -> stop.
    update_config(silence_timeout_seconds=0.8, max_utterance_seconds=15.0)
    audio = await _run([WAKE] + [SPEECH] * 5 + [SILENCE] * 40)
    seconds = len(audio) / 16000
    # 1 wake + 5 speech + 10 silence = 16 chunks = 1.28s; well under the 45 supplied.
    assert seconds < 2.0, f"kept listening through silence ({seconds:.2f}s)"


async def test_short_silence_does_not_end_the_turn():
    # 4 silent chunks (0.32s) < 0.8s: a mid-sentence pause must not stop capture.
    update_config(silence_timeout_seconds=0.8, max_utterance_seconds=15.0)
    audio = await _run([WAKE] + [SPEECH] * 5 + [SILENCE] * 4 + [SPEECH] * 5 + [SILENCE] * 15)
    seconds = len(audio) / 16000
    assert seconds > 1.5, f"stopped on a mid-sentence pause ({seconds:.2f}s)"


async def test_max_utterance_caps_runaway_speech(caplog):
    import logging
    # Continuous speech, never silent: only the runaway guard can stop this.
    _set_timing(silence_timeout_seconds=0.8, max_utterance_seconds=1.0)
    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        audio = await _run([WAKE] + [SPEECH] * 200)
    seconds = len(audio) / 16000
    assert seconds < 2.0, f"runaway guard never fired ({seconds:.2f}s)"
    assert "Max utterance reached" in caplog.text


async def test_silence_and_cap_log_distinctly(caplog):
    import logging
    # The two exits must be tellable apart: one message for both is how the
    # truncation hid in plain sight.
    update_config(silence_timeout_seconds=0.8, max_utterance_seconds=15.0)
    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        await _run([WAKE] + [SPEECH] * 5 + [SILENCE] * 15)
    assert "Silence detected" in caplog.text
    assert "Max utterance reached" not in caplog.text


def test_chunk_seconds_constant():
    from voice.pipeline import _CHUNK_SECONDS
    assert _CHUNK_SECONDS == pytest.approx(0.08)


def test_config_defaults():
    from core.config import get_config
    cfg = get_config()
    assert cfg.silence_timeout_seconds == 0.8
    assert cfg.max_utterance_seconds == 15.0
    assert cfg.prespeech_bail_seconds == 2.0


def test_silence_chunks_threshold_is_retired():
    from core.config import PliaConfig
    assert not hasattr(PliaConfig(), "silence_chunks_threshold")


async def _run_paced(feed, config_kwargs, expect_stt=True):
    """Drive one turn while a producer feeds chunks at real 80ms pacing.

    The other tests in this file pre-queue every chunk, so Queue.get() resolves
    in microseconds and no wall-clock time passes inside the loop — meaning they
    cannot exercise any deadline. This helper is the only way to prove the
    truncation fix is real.

    expect_stt=False is for false-wake paths, which must never reach STT at
    all; returns None in that case.
    """
    _set_timing(**config_kwargs)
    pipeline = _make_pipeline(wake_detects_on=0)
    pipeline._conversation = [{"role": "system", "content": "sys"}]
    q: asyncio.Queue = asyncio.Queue()
    await q.put(WAKE)  # wake must be available immediately
    producer = asyncio.create_task(feed(q))
    try:
        with patch("voice.pipeline.run_turn", new=AsyncMock(return_value=("ok", []))), \
             patch("voice.pipeline.sd"):
            await pipeline._process_loop(q, max_iterations=1)
    finally:
        producer.cancel()
    if not expect_stt:
        assert not pipeline._stt.transcribe.called, \
            "STT ran on audio the loop already knew contained no speech"
        return None
    assert pipeline._stt.transcribe.called, "STT was never called"
    return pipeline._stt.transcribe.call_args[0][0]


async def test_cap_comes_from_max_utterance_not_silence_timeout():
    """The cap must derive from max_utterance_seconds, not silence_timeout_seconds.

    This is the actual regression. With chunks arriving at real 80ms pacing:
      OLD code: deadline = now + silence_timeout_seconds (0.1) -> truncates to ~0.1s
      NEW code: hard_deadline = now + max_utterance_seconds (1.5); silence never
                fires because the speech is continuous -> captures the full ~1s
    Every other test in this file passes on the unfixed code; this one does not.
    """
    async def feed(q):
        for _ in range(12):          # 12 * 80ms = ~0.96s of continuous speech
            await q.put(SPEECH)
            await asyncio.sleep(0.08)  # real pacing — wall-clock must advance

    audio = await _run_paced(feed, dict(silence_timeout_seconds=0.1,
                                        max_utterance_seconds=1.5))
    seconds = len(audio) / 16000
    assert seconds > 0.5, (
        f"captured only {seconds:.2f}s — the cap is still coming from "
        f"silence_timeout_seconds (0.1s), not max_utterance_seconds (1.5s)"
    )


async def test_max_utterance_deadline_fires_on_wall_clock(caplog):
    """The runaway guard must bind on elapsed time, not only on chunk count.

    The two arms are coupled: max_chunks derives from max_utterance_seconds via
    _CHUNK_SECONDS. Feeding at exactly _CHUNK_SECONDS pacing makes them fire
    together, so the chunk arm masks the wall-clock arm. Feeding strictly fewer
    chunks than max_chunks (3 < 5) leaves hard_deadline as the only exit that
    can end this turn — but once the producer stops, captured audio length is
    fixed no matter how long the loop takes to notice, so an assertion on audio
    length alone still proves nothing. What discriminates the bug is *how long
    the loop takes to exit*: on correct code hard_deadline is ~0.4s away, so
    the loop exits quickly; if hard_deadline were still bound to
    silence_timeout_seconds (5.0s, the bug this guards against), the loop would
    idle for ~5s before exiting. Measuring wall-clock elapsed time is the only
    way this test can tell the two apart.
    """
    import logging
    import time

    async def feed(q):
        for _ in range(3):           # 3 chunks, vs max_chunks = ceil(0.4/0.08) = 5
            await q.put(SPEECH)
            await asyncio.sleep(0.08)
        # producer stops; the loop now idles on wait_for until hard_deadline

    start = time.monotonic()
    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        audio = await _run_paced(feed, dict(silence_timeout_seconds=5.0,
                                            max_utterance_seconds=0.4))
    elapsed = time.monotonic() - start
    seconds = len(audio) / 16000
    assert elapsed < 1.5, (
        f"runaway guard took {elapsed:.2f}s to fire — hard_deadline is bound to "
        f"silence_timeout_seconds (5.0s) instead of max_utterance_seconds (0.4s)"
    )
    assert seconds < 1.0, f"unexpectedly captured {seconds:.2f}s of audio"
    assert "Max utterance reached" in caplog.text


async def test_false_wake_rearms_without_waiting_out_the_cap(caplog):
    """A false wake must not hold the mic for the full max_utterance_seconds.

    speech_detected is only set by a chunk above _ENERGY_FLOOR, and the silence
    branch is gated on it — so a wake in a quiet room can never exit via silence.
    Without the pre-speech bail the loop would idle to the cap, deaf to a new wake.

    The bail must also drop what it collected: transcribing 2s of known
    silence would block the event loop on Whisper and flicker "processing" on
    the dashboard for a turn that never happened.
    """
    import logging
    import time

    async def feed(q):
        for _ in range(40):          # pure silence, well past the 2s bail
            await q.put(SILENCE)
            await asyncio.sleep(0.08)

    start = time.monotonic()
    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        await _run_paced(feed, dict(silence_timeout_seconds=0.8,
                                    max_utterance_seconds=15.0,
                                    prespeech_bail_seconds=2.0),
                         expect_stt=False)
    elapsed = time.monotonic() - start
    assert elapsed < 3.0, f"sat deaf for {elapsed:.2f}s after a false wake"
    assert "No speech after wake" in caplog.text
    assert "Max utterance reached" not in caplog.text


async def test_prespeech_bail_is_configurable(caplog):
    """The bail window comes from prespeech_bail_seconds, not a hardcoded 2s."""
    import logging
    import time

    async def feed(q):
        for _ in range(25):          # 2s of silence — past a 0.5s bail, short of 2s
            await q.put(SILENCE)
            await asyncio.sleep(0.08)

    start = time.monotonic()
    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        await _run_paced(feed, dict(silence_timeout_seconds=0.8,
                                    max_utterance_seconds=15.0,
                                    prespeech_bail_seconds=0.5),
                         expect_stt=False)
    elapsed = time.monotonic() - start
    assert elapsed < 1.5, (
        f"bail took {elapsed:.2f}s — prespeech_bail_seconds=0.5 was ignored"
    )
    assert "No speech after wake" in caplog.text


async def test_real_speech_still_exits_via_silence_not_the_bail(caplog):
    """The bail must never pre-empt a real utterance's trailing silence."""
    import logging

    async def feed(q):
        for _ in range(10):
            await q.put(SPEECH)
            await asyncio.sleep(0.08)
        for _ in range(15):
            await q.put(SILENCE)
            await asyncio.sleep(0.08)

    with caplog.at_level(logging.INFO, logger="voice.pipeline"):
        await _run_paced(feed, dict(silence_timeout_seconds=0.8,
                                    max_utterance_seconds=15.0))
    assert "Silence detected" in caplog.text
    assert "No speech after wake" not in caplog.text
