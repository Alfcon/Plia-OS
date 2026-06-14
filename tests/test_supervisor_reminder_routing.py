from core.supervisor import _keyword_route


def test_keyword_route_remind_me_to():
    assert _keyword_route("remind me to take my medication at 3pm") == "reminder"


def test_keyword_route_set_a_reminder():
    assert _keyword_route("set a reminder for tomorrow morning") == "reminder"


def test_keyword_route_dont_let_me_forget():
    assert _keyword_route("don't let me forget to call the doctor") == "reminder"


def test_keyword_route_remind_me_bare_routes_to_llm():
    # "remind me what we discussed" — bare "remind me" without "to" falls through to LLM
    assert _keyword_route("remind me what we discussed") is None


def test_keyword_route_alert_me_routes_to_llm():
    # "alert me" is too ambiguous (home automation, monitoring) — falls through to LLM
    assert _keyword_route("alert me when the timer goes off") is None


def test_keyword_route_calendar_unaffected():
    assert _keyword_route("schedule a meeting for Monday") == "calendar"
