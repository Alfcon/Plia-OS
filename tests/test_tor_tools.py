from unittest.mock import patch


def test_enable_tor_calls_manager_enable():
    with patch("core.tor_manager.enable", return_value="Tor enabled. Exit node: 185.220.1.1") as mock_en:
        from modules.tor_tools import enable_tor
        result = enable_tor()
    mock_en.assert_called_once()
    assert "enabled" in result.lower()


def test_disable_tor_calls_manager_disable():
    with patch("core.tor_manager.disable", return_value="Tor disabled. Clearnet restored.") as mock_dis:
        from modules.tor_tools import disable_tor
        result = disable_tor()
    mock_dis.assert_called_once()
    assert "disabled" in result.lower()


def test_tor_status_enabled():
    with patch("core.tor_manager.get_status", return_value={
        "enabled": True,
        "kill_switch_active": False,
        "exit_ip": "185.220.1.1",
    }):
        from modules.tor_tools import tor_status
        result = tor_status()
    assert "enabled" in result.lower()
    assert "185.220.1.1" in result


def test_tor_status_disabled():
    with patch("core.tor_manager.get_status", return_value={
        "enabled": False,
        "kill_switch_active": False,
        "exit_ip": None,
    }):
        from modules.tor_tools import tor_status
        result = tor_status()
    assert "disabled" in result.lower()


def test_tor_status_kill_switch_active():
    with patch("core.tor_manager.get_status", return_value={
        "enabled": False,
        "kill_switch_active": True,
        "exit_ip": None,
    }):
        from modules.tor_tools import tor_status
        result = tor_status()
    assert "kill switch" in result.lower() or "blocked" in result.lower()


def test_tor_tools_registered_as_tools(reset_registry):
    import sys
    import importlib
    from core.registry import set_loading_module, list_tools

    # Remove module from cache if present, so we can import it fresh
    if "modules.tor_tools" in sys.modules:
        del sys.modules["modules.tor_tools"]

    set_loading_module("tor_tools")
    try:
        import modules.tor_tools  # noqa: F401
    finally:
        set_loading_module("")

    tools = list_tools()
    assert "enable_tor" in tools
    assert "disable_tor" in tools
    assert "tor_status" in tools
