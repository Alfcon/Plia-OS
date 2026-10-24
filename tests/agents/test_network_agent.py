import pytest
from unittest.mock import AsyncMock, patch
from agents.network import network_node


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
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json at all"}
        update = await network_node(_state("do something with my mac"))
    assert update["active_agent"] == "network"
    result = "\n".join(update["tool_results"])
    assert "show my mac" in result.lower() or "randomize" in result.lower()


@pytest.mark.asyncio
async def test_missing_action_field_returns_fallback():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"interface": "eth0"}'}
        update = await network_node(_state("mac something"))
    assert update["active_agent"] == "network"
    result = "\n".join(update["tool_results"])
    assert "show my mac" in result.lower() or "randomize" in result.lower()


@pytest.mark.asyncio
async def test_action_show_no_interface_calls_show_mac_with_empty_string():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.network.show_mac", return_value="eth0: aa:bb:cc:dd:ee:ff") as mock_show:
        mock_llm.return_value = {"content": '{"action":"show","interface":null,"mac":null}'}
        update = await network_node(_state("show my mac address"))
    mock_show.assert_called_once_with("")
    assert update["active_agent"] == "network"
    result = "\n".join(update["tool_results"])
    assert "eth0" in result
    assert any(r.startswith("[network]") for r in update["tool_results"])


@pytest.mark.asyncio
async def test_action_randomize_named_interface():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.network.randomize_mac", return_value="wlan0: old → new") as mock_rand:
        mock_llm.return_value = {"content": '{"action":"randomize","interface":"wlan0","mac":null}'}
        update = await network_node(_state("randomize mac on wlan0"))
    mock_rand.assert_called_once_with("wlan0")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_action_set_passes_interface_and_mac():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.network.set_mac", return_value="eth0: set to AA:BB:CC:DD:EE:FF") as mock_set:
        mock_llm.return_value = {"content": '{"action":"set","interface":"eth0","mac":"AA:BB:CC:DD:EE:FF"}'}
        update = await network_node(_state("set mac to AA:BB:CC:DD:EE:FF"))
    mock_set.assert_called_once_with("eth0", "AA:BB:CC:DD:EE:FF")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_action_restore_no_interface_calls_restore_with_empty_string():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.network.restore_mac", return_value="eth0: restored to aa:bb:cc:dd:ee:ff") as mock_rest:
        mock_llm.return_value = {"content": '{"action":"restore","interface":null,"mac":null}'}
        update = await network_node(_state("restore my mac"))
    mock_rest.assert_called_once_with("")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.network.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.network.show_mac", return_value="eth0: aa:bb:cc:dd:ee:ff"):
        mock_llm.return_value = {"content": '{"action":"show","interface":null,"mac":null}'}
        state = _state("show my mac")
        state["tool_results"] = ["[memory]\nsome prior result"]
        update = await network_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nsome prior result"
