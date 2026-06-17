import pytest
from unittest.mock import patch
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


_TABLE = "| Interface | MAC Address | Type |\n|-----------|-------------|------|\n| eth0 | aa:bb:cc:dd:ee:ff | Ethernet |"


# --- show / list ---

@pytest.mark.asyncio
async def test_show_no_interface_calls_list_macs():
    with patch("agents.network.list_macs", return_value=_TABLE) as mock_list:
        update = await network_node(_state("show my mac address"))
    mock_list.assert_called_once_with()
    assert update["active_agent"] == "network"
    assert any(r.startswith("[network]") for r in update["tool_results"])
    assert "eth0" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_show_named_interface_calls_show_mac():
    with patch("agents.network.show_mac", return_value="wlan0: 11:22:33:44:55:66") as mock_show:
        update = await network_node(_state("show mac on wlan0"))
    mock_show.assert_called_once_with("wlan0")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_list_keyword_calls_list_macs():
    with patch("agents.network.list_macs", return_value=_TABLE) as mock_list:
        update = await network_node(_state("list all network interfaces"))
    mock_list.assert_called_once_with()


@pytest.mark.asyncio
async def test_ambiguous_defaults_to_list_macs():
    with patch("agents.network.list_macs", return_value=_TABLE) as mock_list:
        update = await network_node(_state("do something with my mac"))
    mock_list.assert_called_once_with()


# --- randomize ---

@pytest.mark.asyncio
async def test_randomize_keyword_no_interface():
    with patch("agents.network.randomize_mac", return_value="eth0: old → new") as mock_rand:
        update = await network_node(_state("randomize mac"))
    mock_rand.assert_called_once_with("")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_randomize_named_interface():
    with patch("agents.network.randomize_mac", return_value="wlan0: old → new") as mock_rand:
        update = await network_node(_state("randomize mac on wlan0"))
    mock_rand.assert_called_once_with("wlan0")


@pytest.mark.asyncio
async def test_change_keyword_routes_to_randomize():
    with patch("agents.network.randomize_mac", return_value="eth0: old → new") as mock_rand:
        update = await network_node(_state("change mac address"))
    mock_rand.assert_called_once_with("")


@pytest.mark.asyncio
async def test_mask_keyword_routes_to_randomize():
    with patch("agents.network.randomize_mac", return_value="eth0: old → new") as mock_rand:
        update = await network_node(_state("mask my mac"))
    mock_rand.assert_called_once_with("")


@pytest.mark.asyncio
async def test_spoof_keyword_routes_to_randomize():
    with patch("agents.network.randomize_mac", return_value="eth0: old → new") as mock_rand:
        update = await network_node(_state("spoof mac on eth0"))
    mock_rand.assert_called_once_with("eth0")


@pytest.mark.asyncio
async def test_fake_keyword_routes_to_randomize():
    with patch("agents.network.randomize_mac", return_value="eth0: old → new") as mock_rand:
        update = await network_node(_state("fake my mac address"))
    mock_rand.assert_called_once_with("")


# --- set ---

@pytest.mark.asyncio
async def test_set_mac_no_interface():
    with patch("agents.network.set_mac", return_value="eth0: set to AA:BB:CC:DD:EE:FF") as mock_set:
        update = await network_node(_state("set mac to AA:BB:CC:DD:EE:FF"))
    mock_set.assert_called_once_with("", "AA:BB:CC:DD:EE:FF")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_set_mac_with_interface():
    with patch("agents.network.set_mac", return_value="eth0: set to AA:BB:CC:DD:EE:FF") as mock_set:
        update = await network_node(_state("set mac to AA:BB:CC:DD:EE:FF on eth0"))
    mock_set.assert_called_once_with("eth0", "AA:BB:CC:DD:EE:FF")


@pytest.mark.asyncio
async def test_set_mac_case_insensitive():
    with patch("agents.network.set_mac", return_value="eth0: set to aa:bb:cc:dd:ee:ff") as mock_set:
        update = await network_node(_state("use aa:bb:cc:dd:ee:ff on wlan0"))
    mock_set.assert_called_once_with("wlan0", "aa:bb:cc:dd:ee:ff")


# --- restore ---

@pytest.mark.asyncio
async def test_restore_no_interface():
    with patch("agents.network.restore_mac", return_value="eth0: restored to aa:bb:cc:dd:ee:ff") as mock_rest:
        update = await network_node(_state("restore my mac"))
    mock_rest.assert_called_once_with("")
    assert update["active_agent"] == "network"


@pytest.mark.asyncio
async def test_restore_named_interface():
    with patch("agents.network.restore_mac", return_value="eth0: restored") as mock_rest:
        update = await network_node(_state("restore mac on eth0"))
    mock_rest.assert_called_once_with("eth0")


@pytest.mark.asyncio
async def test_revert_keyword_routes_to_restore():
    with patch("agents.network.restore_mac", return_value="eth0: restored") as mock_rest:
        update = await network_node(_state("revert mac address"))
    mock_rest.assert_called_once_with("")


@pytest.mark.asyncio
async def test_original_keyword_routes_to_restore():
    with patch("agents.network.restore_mac", return_value="eth0: restored") as mock_rest:
        update = await network_node(_state("use original mac"))
    mock_rest.assert_called_once_with("")


# --- state ---

@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.network.list_macs", return_value=_TABLE):
        state = _state("show my mac")
        state["tool_results"] = ["[memory]\nsome prior result"]
        update = await network_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nsome prior result"
    assert update["tool_results"][1].startswith("[network]")


@pytest.mark.asyncio
async def test_result_prefixed_with_network_tag():
    with patch("agents.network.list_macs", return_value=_TABLE):
        update = await network_node(_state("list macs"))
    assert update["tool_results"][-1].startswith("[network]")
