"""The WiFi specialist must distinguish "show my saved password" from
"get access to a network I don't have the password for"."""
import asyncio
import json
from unittest.mock import patch

import agents.wifi as wifi


def _state(text):
    return {"messages": [{"role": "user", "content": text}], "tool_results": []}


def _parser(action):
    async def fake_llm(_messages):
        return {"content": json.dumps({
            "action": action, "interface": None, "ssid": None, "password": None,
        })}
    return fake_llm


def test_wifi_agent_password_action_returns_saved_password():
    with patch.object(wifi, "call_llm", side_effect=_parser("password")), \
         patch("modules.network_check_tools.check_wifi_password",
                      return_value="SSID/connection: Auto Contarino\nWiFi password: Ca55andra!") as check:
        out = asyncio.run(wifi.wifi_node(_state("what is my wifi password?")))
    assert "Ca55andra!" in out["tool_results"][-1]
    assert out["active_agent"] == "wifi"
    check.assert_called_once_with()


def test_wifi_agent_gain_still_uses_access_recovery():
    with patch.object(wifi, "call_llm", side_effect=_parser("gain")), \
         patch("modules.wireless_tools.gain_wifi_access", return_value="recovered via WPS") as gain, \
         patch("modules.network_check_tools.check_wifi_password") as check:
        out = asyncio.run(wifi.wifi_node(_state("get access to a network I don't have the password for")))
    assert "recovered via WPS" in out["tool_results"][-1]
    gain.assert_called_once_with("", "")
    check.assert_not_called()


def test_wifi_password_works_without_llm():
    with patch.object(wifi, "call_llm", side_effect=RuntimeError("ollama down")) as llm, \
         patch("modules.network_check_tools.check_wifi_password",
                      return_value="SSID/connection: Auto Contarino\nWiFi password: Ca55andra!"):
        out = asyncio.run(wifi.wifi_node(_state("what is my wifi password?")))
    assert "Ca55andra!" in out["tool_results"][-1]
    llm.assert_not_called()          # deterministic keyword path, no LLM dependency
