def test_tor_enabled_default_false(isolate_config_file):
    from core.config import get_config, update_config
    assert get_config().tor_enabled is False
    update_config(tor_enabled=True)
    assert get_config().tor_enabled is True


def test_briefing_news_topic_default(isolate_config_file):
    from core.config import get_config, update_config
    assert get_config().briefing_news_topic == "breaking news"
    update_config(briefing_news_topic="technology")
    assert get_config().briefing_news_topic == "technology"
