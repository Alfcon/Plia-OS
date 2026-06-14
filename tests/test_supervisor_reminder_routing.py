from core.supervisor import _keyword_route


def test_keyword_route_remind_me():
    assert _keyword_route("remind me to take my medication at 3pm") == "reminder"


def test_keyword_route_set_a_reminder():
    assert _keyword_route("set a reminder for tomorrow morning") == "reminder"


def test_keyword_route_dont_let_me_forget():
    assert _keyword_route("don't let me forget to call the doctor") == "reminder"


def test_keyword_route_alert_me():
    assert _keyword_route("alert me when the timer goes off") == "reminder"


def test_keyword_route_calendar_unaffected():
    # "schedule a" should still route to calendar, not reminder
    assert _keyword_route("schedule a meeting for Monday") == "calendar"
