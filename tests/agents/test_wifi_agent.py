import pytest
from unittest.mock import AsyncMock, patch
from agents.wifi import wifi_node


def _state(user_text: str, prior_results: list | None = None) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": prior_results or [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await wifi_node(_state("wifi stuff"))
    assert update["active_agent"] == "wifi"
    assert "wifi" in "\n".join(update["tool_results"]).lower()


@pytest.mark.asyncio
async def test_unknown_action_returns_fallback():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"action":"unknown","interface":null}'}
        update = await wifi_node(_state("do something wifi"))
    assert update["active_agent"] == "wifi"
    result = "\n".join(update["tool_results"])
    assert "couldn't parse" in result.lower()


@pytest.mark.asyncio
async def test_action_status_calls_wifi_status():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.wifi.wifi_status", return_value="SSID: MyNet\nSignal: 80%") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"status","interface":null}'}
        update = await wifi_node(_state("what's my wifi status"))
    mock_fn.assert_called_once_with()
    assert update["active_agent"] == "wifi"
    assert any(r.startswith("[wifi]") for r in update["tool_results"])
    assert "MyNet" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_action_scan_no_interface():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.wifi.scan_wifi", return_value="MyNet  90%  WPA2  ch6") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"scan","interface":null}'}
        update = await wifi_node(_state("scan for wifi networks"))
    mock_fn.assert_called_once_with("")
    assert update["active_agent"] == "wifi"


@pytest.mark.asyncio
async def test_action_scan_named_interface():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.wifi.scan_wifi", return_value="MyNet  90%  WPA2  ch6") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"scan","interface":"wlan0"}'}
        update = await wifi_node(_state("scan on wlan0"))
    mock_fn.assert_called_once_with("wlan0")
    assert update["active_agent"] == "wifi"


@pytest.mark.asyncio
async def test_action_interfaces_calls_list():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.wifi.list_wifi_interfaces", return_value="wlan0  wifi  connected") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"interfaces","interface":null}'}
        update = await wifi_node(_state("list wifi interfaces"))
    mock_fn.assert_called_once_with()
    assert update["active_agent"] == "wifi"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.wifi.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.wifi.wifi_status", return_value="connected"):
        mock_llm.return_value = {"content": '{"action":"status","interface":null}'}
        state = _state("wifi status")
        state["tool_results"] = ["[memory]\nprior"]
        update = await wifi_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nprior"
