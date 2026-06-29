from __future__ import annotations
import pytest
from core.intent_classifier import classify_intent, THRESHOLD


def test_returns_tuple():
    intent, conf = classify_intent("remind me to call mom at 3pm")
    assert isinstance(intent, (str, type(None)))
    assert isinstance(conf, float)


def test_confidence_in_range():
    _, conf = classify_intent("turn on the living room lights")
    assert 0.0 <= conf <= 1.0


def test_reminder_intent():
    intent, conf = classify_intent("remind me to take my medication at 8am")
    assert conf >= THRESHOLD
    assert intent == "reminder"


def test_home_intent():
    intent, conf = classify_intent("turn off all the lights in the kitchen")
    assert conf >= THRESHOLD
    assert intent == "home"


def test_memory_intent():
    intent, conf = classify_intent("remember that my dog's name is Bruno")
    assert conf >= THRESHOLD
    assert intent == "memory"


def test_weather_intent():
    intent, conf = classify_intent("what is the weather like today")
    assert conf >= THRESHOLD
    assert intent == "weather"


def test_calendar_intent():
    intent, conf = classify_intent("add a meeting to my calendar for Friday")
    assert conf >= THRESHOLD
    assert intent == "calendar"


def test_web_intent():
    intent, conf = classify_intent("search the web for best python frameworks")
    assert conf >= THRESHOLD
    assert intent == "web"


def test_empty_input_no_crash():
    intent, conf = classify_intent("")
    assert conf >= 0.0


def test_gibberish_low_confidence_or_valid():
    _, conf = classify_intent("xyzzy frumpkin blorbzorp")
    assert 0.0 <= conf <= 1.0
