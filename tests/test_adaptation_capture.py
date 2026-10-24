from __future__ import annotations
import pytest


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    """Redirect chat_history to a temp DB so tests never touch data/."""
    import agents.chat_history as ch
    monkeypatch.setattr(ch, "_DB_PATH", tmp_path / "chat_history.db")
    ch._init_db()
    return ch


def test_get_message_pair_returns_user_and_assistant(history_db):
    history_db.add_message("user", "what's the weather")
    history_db.add_message("assistant", "Sunny, 22C.")
    rows = history_db.get_recent_with_id(10, True)
    assistant_id = rows[-1]["id"]

    pair = history_db.get_message_pair(assistant_id)
    assert pair is not None
    user_msg, assistant_msg = pair
    assert user_msg["content"] == "what's the weather"
    assert user_msg["role"] == "user"
    assert assistant_msg["content"] == "Sunny, 22C."
    assert assistant_msg["id"] == assistant_id


def test_get_message_pair_rejects_user_message(history_db):
    history_db.add_message("user", "hello")
    rows = history_db.get_recent_with_id(10, True)
    assert history_db.get_message_pair(rows[-1]["id"]) is None


def test_get_message_pair_unknown_id(history_db):
    assert history_db.get_message_pair(9999) is None


def test_get_message_pair_no_preceding_user(history_db):
    history_db.add_message("assistant", "orphan greeting")
    rows = history_db.get_recent_with_id(10, True)
    assert history_db.get_message_pair(rows[-1]["id"]) is None


import logging
from unittest.mock import AsyncMock, MagicMock, patch
from core.config import update_config


@pytest.fixture
def adaptation_on():
    update_config(adaptation_enabled=True)
    yield


def _msgs(*pairs):
    out = [{"role": "system", "content": "sys"}]
    for role, content in pairs:
        out.append({"role": role, "content": content})
    return out


@pytest.mark.asyncio
async def test_non_correction_costs_zero_llm_calls(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.1
    llm = AsyncMock()
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "what's the weather"), ("assistant", "Sunny."), ("user", "and tomorrow")),
            "and tomorrow", "Rainy.",
        )
    llm.assert_not_called()
    store.add_intent_correction.assert_not_called()


@pytest.mark.parametrize("utterance", [
    "no, I meant the lights",
    "No. I meant the lamp.",
    "no I said the bedroom",
    "too long",
    "Too verbose.",
    "be shorter",
    "shorter please",
    "actually, the kitchen one",
    "i meant the lights",
    "that is not what I said",
    "that's not right",
    "thats not it",
    "wrong, I said bedroom",
])
def test_correction_regex_matches_correction_shaped(utterance):
    from core.supervisor import _CORRECTION_RE
    assert _CORRECTION_RE.search(utterance)


@pytest.mark.parametrize("utterance", [
    # Each of these matched before the anchor fix and would have burned an
    # LLM call — and risked a hallucinated relabel — on ordinary conversation.
    "the movie was too long honestly",
    "my commute felt too long today",
    "how long is the meeting, it runs too long",
    "no thanks, that is fine",
    "no thank you",
    "no problem",
    "no worries",
    "and tomorrow",
    "turn on the lights",
    "what is the weather",
    "that is not bad at all",
])
def test_correction_regex_ignores_ordinary_conversation(utterance):
    from core.supervisor import _CORRECTION_RE
    assert not _CORRECTION_RE.search(utterance)


@pytest.mark.asyncio
async def test_correction_relabels_previous_utterance(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.1
    llm = AsyncMock(return_value={"content": '{"intent": "home", "style_note": null}'})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "hit the lamp"), ("assistant", "Searching the web..."), ("user", "no, I meant the lights")),
            "no, I meant the lights", "Turning on the lights.",
        )
    # The PRIOR utterance is what gets relabelled — not the correction text.
    store.add_intent_correction.assert_called_once_with("hit the lamp", "home", "chat")


@pytest.mark.asyncio
async def test_correction_with_style_note_captures_corrected_response(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.1
    llm = AsyncMock(return_value={"content": '{"intent": null, "style_note": "be shorter"}'})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "what's the time"), ("assistant", "It is currently..."), ("user", "too long")),
            "too long", "3pm.",
        )
    store.add_style_exemplar.assert_called_once_with("what's the time", "3pm.", 1, "chat")
    store.add_intent_correction.assert_not_called()


@pytest.mark.asyncio
async def test_correction_unknown_intent_writes_nothing(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.1
    llm = AsyncMock(return_value={"content": '{"intent": "bogus", "style_note": null}'})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "hit the lamp"), ("assistant", "?"), ("user", "no, I meant the lights")),
            "no, I meant the lights", "ok",
        )
    store.add_intent_correction.assert_not_called()


@pytest.mark.asyncio
async def test_correction_bad_json_writes_nothing_and_does_not_raise(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.1
    llm = AsyncMock(return_value={"content": "not json at all"})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "hit the lamp"), ("assistant", "?"), ("user", "no, I meant the lights")),
            "no, I meant the lights", "ok",
        )
    store.add_intent_correction.assert_not_called()
    store.add_style_exemplar.assert_not_called()


@pytest.mark.asyncio
async def test_rephrase_writes_negative_only(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.9  # above the 0.85 default
    store.has_rephrase.return_value = False
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "what is the weather"), ("assistant", "I don't know."), ("user", "what's the weather")),
            "what's the weather", "Sunny.",
        )
    store.add_style_exemplar.assert_called_once_with(
        "what is the weather", "I don't know.", -1, "rephrase"
    )
    store.add_intent_correction.assert_not_called()


@pytest.mark.asyncio
async def test_rephrase_below_threshold_writes_nothing(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.3
    store.has_rephrase.return_value = False
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "what is the weather"), ("assistant", "Sunny."), ("user", "turn on the lights")),
            "turn on the lights", "Done.",
        )
    store.add_style_exemplar.assert_not_called()


@pytest.mark.asyncio
async def test_rephrase_chain_suppressed(adaptation_on):
    store = MagicMock()
    store.similarity.return_value = 0.9
    store.has_rephrase.return_value = True  # prior turn was already a rephrase
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "what is the weather"), ("assistant", "?"), ("user", "what's the weather")),
            "what's the weather", "Sunny.",
        )
    store.add_style_exemplar.assert_not_called()


@pytest.mark.asyncio
async def test_no_prior_exchange_writes_nothing(adaptation_on):
    store = MagicMock()
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(_msgs(("user", "no, I meant the lights")), "no, I meant the lights", "ok")
    store.add_intent_correction.assert_not_called()
    store.add_style_exemplar.assert_not_called()


@pytest.mark.asyncio
async def test_capture_disabled_never_touches_store():
    store = MagicMock()
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        await _adaptation_capture(
            _msgs(("user", "hit the lamp"), ("assistant", "?"), ("user", "no, I meant the lights")),
            "no, I meant the lights", "ok",
        )
    store.add_intent_correction.assert_not_called()
    store.similarity.assert_not_called()


@pytest.mark.asyncio
async def test_capture_swallows_store_errors(adaptation_on, caplog):
    with patch("agents.adaptation.get_adaptation_store", side_effect=RuntimeError("boom")), \
         patch("core.supervisor.call_llm", new=AsyncMock()):
        from core.supervisor import _adaptation_capture
        with caplog.at_level(logging.ERROR, logger="core.supervisor"):
            await _adaptation_capture(
                _msgs(("user", "hit the lamp"), ("assistant", "?"), ("user", "no, I meant the lights")),
                "no, I meant the lights", "ok",
            )
    # Assert the failure path actually ran. Without this the test would also
    # pass if _adaptation_capture silently stopped doing anything at all.
    assert "Adaptation capture failed" in caplog.text


@pytest.mark.asyncio
async def test_capture_swallows_write_errors(adaptation_on, caplog):
    store = MagicMock()
    store.similarity.return_value = 0.1
    store.add_intent_correction.side_effect = RuntimeError("db locked")
    llm = AsyncMock(return_value={"content": '{"intent": "home", "style_note": null}'})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _adaptation_capture
        with caplog.at_level(logging.ERROR, logger="core.supervisor"):
            await _adaptation_capture(
                _msgs(("user", "hit the lamp"), ("assistant", "?"), ("user", "no, I meant the lights")),
                "no, I meant the lights", "ok",
            )
    store.add_intent_correction.assert_called_once()  # it was attempted
    assert "Adaptation capture failed" in caplog.text  # and the raise was caught
