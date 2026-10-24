import json
import pytest
from agents.llm import parse_llm_json


def test_bare_json():
    assert parse_llm_json('{"op": "list_states"}') == {"op": "list_states"}


def test_fence_with_json_tag():
    content = '```json\n{"op": "call_service", "domain": "light"}\n```'
    assert parse_llm_json(content) == {"op": "call_service", "domain": "light"}


def test_fence_no_language_tag():
    content = '```\n{"key": "value"}\n```'
    assert parse_llm_json(content) == {"key": "value"}


def test_fence_uppercase_language_tag():
    content = '```JSON\n{"op": "get_state"}\n```'
    assert parse_llm_json(content) == {"op": "get_state"}


def test_prose_preamble_before_fence():
    content = 'Sure! Here is the JSON:\n```json\n{"op": "list_states"}\n```'
    assert parse_llm_json(content) == {"op": "list_states"}


def test_empty_first_fence_skipped_real_second_fence_used():
    content = "```\n```json\n{\"op\": \"call_service\"}\n```"
    assert parse_llm_json(content) == {"op": "call_service"}


def test_non_dict_list_returns_empty():
    assert parse_llm_json("[1, 2, 3]") == {}


def test_non_dict_null_returns_empty():
    assert parse_llm_json("null") == {}


def test_none_content_returns_empty():
    assert parse_llm_json(None) == {}


def test_empty_string_returns_empty():
    assert parse_llm_json("") == {}


def test_whitespace_only_returns_empty():
    assert parse_llm_json("   ") == {}


def test_malformed_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json("not valid json")


def test_malformed_json_in_fence_falls_through_to_raw():
    content = "```json\nnot json\n```"
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json(content)


def test_multiple_fences_returns_first_valid_dict():
    content = '```json\n{"first": true}\n```\n```json\n{"second": true}\n```'
    assert parse_llm_json(content) == {"first": True}
