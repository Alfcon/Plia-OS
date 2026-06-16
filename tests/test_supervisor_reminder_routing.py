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


def test_keyword_route_set_a_timer_goes_to_respond():
    assert _keyword_route("set a timer for 5 minutes") == "respond"


def test_keyword_route_start_a_timer_goes_to_respond():
    assert _keyword_route("start a timer for pasta") == "respond"


def test_keyword_route_timer_for_goes_to_respond():
    assert _keyword_route("timer for 10 minutes") == "respond"


def test_keyword_route_mute_goes_to_respond():
    assert _keyword_route("mute the audio") == "respond"


def test_keyword_route_volume_up_goes_to_respond():
    assert _keyword_route("turn volume up please") == "respond"


def test_keyword_route_system_info_goes_to_respond():
    assert _keyword_route("how much ram am I using") == "respond"


def test_keyword_route_remember_this():
    assert _keyword_route("remember this: my dog is named Rex") == "memory"


def test_keyword_route_store_that():
    assert _keyword_route("store that in memory") == "memory"


def test_keyword_route_save_that():
    assert _keyword_route("save that for later") == "memory"


def test_keyword_route_read_this_article():
    assert _keyword_route("read this article https://example.com") == "web"


def test_keyword_route_what_does_this_page():
    assert _keyword_route("what does this page say https://news.com") == "web"


def test_keyword_route_summarize_url():
    assert _keyword_route("summarize this url for me https://blog.com") == "web"
