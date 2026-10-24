import json
from unittest.mock import MagicMock, patch


def _mock_response(payload_text):
    r = MagicMock()
    r.json.return_value = {"message": {"content": payload_text}}
    return r


ITEMS = [
    {"from": "Jane <jane@co.com>", "subject": "Contract sign-off", "body": "Need the SOW signed today."},
    {"from": "News <news@list.com>", "subject": "Weekly digest", "body": "Ten links you missed."},
]


def test_triage_parses_valid_json():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "high", "category": "work", "spam": False,
         "summary": "Wants SOW signed today.", "draft": "Hi Jane, signing now."},
        {"urgency": "low", "category": "newsletter", "spam": False,
         "summary": "Weekly link digest.", "draft": "should be dropped"},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert len(out) == 2
    assert out[0]["urgency"] == "high"
    assert out[0]["category"] == "work"
    assert out[0]["draft"].startswith("Hi Jane")
    assert out[1]["urgency"] == "low"
    assert out[1]["draft"] == ""  # non-high draft forced empty


def test_triage_extracts_array_from_prose():
    from agents.email_triage import triage_messages
    payload = 'Sure! Here you go:\n[{"urgency":"normal","category":"personal","spam":false,"summary":"Hi.","draft":""},{"urgency":"low","category":"social","spam":true,"summary":"Ad.","draft":""}]\nHope that helps.'
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert len(out) == 2
    assert out[0]["category"] == "personal"
    assert out[1]["spam"] is True


def test_triage_normalizes_unknown_values():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "URGENT!!!", "category": "banking", "spam": "yes",
         "summary": "x", "draft": ""},
        {"urgency": "high", "category": "work", "spam": 0, "summary": "y", "draft": "keep me"},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert out[0]["urgency"] == "normal"     # unknown urgency -> normal
    assert out[0]["category"] == "other"     # unknown category -> other
    assert out[0]["spam"] is True            # truthy coerced to bool
    assert out[1]["spam"] is False
    assert out[1]["draft"] == "keep me"      # high keeps its draft


def test_triage_pads_short_array():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "high", "category": "work", "spam": False, "summary": "one", "draft": "d"},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert len(out) == 2                       # padded to input length
    assert out[1]["urgency"] == "normal"       # fallback
    assert out[1]["draft"] == ""


def test_triage_truncates_long_array():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "low", "category": "work", "spam": False, "summary": "a", "draft": ""},
        {"urgency": "low", "category": "work", "spam": False, "summary": "b", "draft": ""},
        {"urgency": "low", "category": "work", "spam": False, "summary": "c", "draft": ""},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert len(out) == 2                       # truncated to input length
    assert out[0]["summary"] == "a"
    assert out[1]["summary"] == "b"


def test_triage_malformed_json_falls_back():
    from agents.email_triage import triage_messages
    with patch("httpx.post", return_value=_mock_response("not json at all")):
        out = triage_messages(ITEMS)
    assert len(out) == 2
    for r, item in zip(out, ITEMS):
        assert r["urgency"] == "normal"
        assert r["category"] == "other"
        assert r["spam"] is False
        assert r["draft"] == ""
        assert r["summary"]                     # non-empty fallback summary


def test_triage_http_error_falls_back():
    from agents.email_triage import triage_messages
    with patch("httpx.post", side_effect=RuntimeError("boom")):
        out = triage_messages(ITEMS)
    assert len(out) == 2
    assert all(r["urgency"] == "normal" for r in out)


def test_triage_empty_input():
    from agents.email_triage import triage_messages
    assert triage_messages([]) == []


def test_triage_makes_exactly_one_llm_call():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "low", "category": "work", "spam": False, "summary": "a", "draft": ""},
        {"urgency": "low", "category": "work", "spam": False, "summary": "b", "draft": ""},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)) as m:
        triage_messages(ITEMS)
    assert m.call_count == 1   # one batched call, never per-email


def test_triage_spam_string_false_not_flipped():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        {"urgency": "low", "category": "work", "spam": "false", "summary": "a", "draft": ""},
        {"urgency": "low", "category": "social", "spam": "yes", "summary": "b", "draft": ""},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert out[0]["spam"] is False   # string "false" must NOT become True
    assert out[1]["spam"] is True


def test_triage_non_dict_array_element_falls_back():
    from agents.email_triage import triage_messages
    payload = json.dumps([
        "oops not an object",
        {"urgency": "high", "category": "work", "spam": False, "summary": "ok", "draft": "d"},
    ])
    with patch("httpx.post", return_value=_mock_response(payload)):
        out = triage_messages(ITEMS)
    assert len(out) == 2
    assert out[0]["urgency"] == "normal"   # non-dict element coerced to fallback
    assert out[1]["urgency"] == "high"


def test_triage_non_str_body_never_raises():
    from agents.email_triage import triage_messages
    weird = [{"from": ["x"], "subject": None, "body": ["not", "a", "string"]}]
    with patch("httpx.post", return_value=_mock_response("garbage")):
        out = triage_messages(weird)   # must not raise
    assert len(out) == 1
    assert out[0]["urgency"] == "normal"
