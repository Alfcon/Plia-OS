from __future__ import annotations
import pytest
from voice.text_utils import truncate_for_tts


def test_no_limit_passthrough():
    text = "Hello world. This is a long sentence that should not be truncated."
    assert truncate_for_tts(text, 0) == text


def test_negative_limit_passthrough():
    text = "Some text here."
    assert truncate_for_tts(text, -1) == text


def test_short_text_passthrough():
    text = "Short text."
    assert truncate_for_tts(text, 100) == text


def test_truncates_at_sentence_boundary():
    text = "First sentence. Second sentence. Third sentence. Fourth sentence."
    result = truncate_for_tts(text, 5)
    assert result.startswith("First sentence.")
    assert "see dashboard" in result


def test_truncates_at_exclamation():
    text = "Hello! World is great. This is extra text that should be cut off here."
    result = truncate_for_tts(text, 3)
    assert result.endswith("(see dashboard for full response)")


def test_exact_word_count_no_truncation():
    text = "one two three"
    assert truncate_for_tts(text, 3) == text


def test_one_over_word_count_truncates():
    text = "one two three four"
    result = truncate_for_tts(text, 3)
    assert "see dashboard" in result


def test_no_sentence_boundary_uses_ellipsis():
    text = "word1 word2 word3 word4 word5"
    result = truncate_for_tts(text, 3)
    assert "see dashboard" in result
    assert "word1" in result
