def test_tor_enabled_default_false(isolate_config_file):
    from core.config import get_config, update_config
    assert get_config().tor_enabled is False
    update_config(tor_enabled=True)
    assert get_config().tor_enabled is True
