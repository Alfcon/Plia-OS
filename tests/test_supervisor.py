from core.supervisor import _keyword_route


def test_proactive_keywords_route_to_respond():
    assert _keyword_route("enable proactive") == "respond"
    assert _keyword_route("disable proactive") == "respond"
    assert _keyword_route("proactive status") == "respond"
    assert _keyword_route("stop interrupting me") == "respond"
    assert _keyword_route("pause suggestions") == "respond"
    assert _keyword_route("resume suggestions") == "respond"
