from core.supervisor import _keyword_route


def test_proactive_keywords_route_to_respond():
    assert _keyword_route("enable proactive") == "respond"
    assert _keyword_route("disable proactive") == "respond"
    assert _keyword_route("proactive status") == "respond"
    assert _keyword_route("stop interrupting me") == "respond"
    assert _keyword_route("pause suggestions") == "respond"
    assert _keyword_route("resume suggestions") == "respond"


def test_courtesies_route_to_respond():
    # A bare "Thank you." after weather turns used to echo the weather report.
    assert _keyword_route("Thank you.") == "respond"
    assert _keyword_route("thanks") == "respond"
    assert _keyword_route("no thanks") == "respond"
    assert _keyword_route("never mind") == "respond"
    assert _keyword_route("good night") == "respond"
    assert _keyword_route("goodbye") == "respond"


def test_task_intents_not_shadowed_by_courtesy_keywords():
    assert _keyword_route("what's the weather") == "weather"
    assert _keyword_route("turn on the lights") == "home"
    assert _keyword_route("remind me to call mom") == "reminder"
