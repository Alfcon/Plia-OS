import pytest
from unittest.mock import AsyncMock, patch
from core.config import reset_config, update_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def _state(user_text):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_home_node_unconfigured_returns_guidance():
    from agents.home import home_node
    update = await home_node(_state("turn on the lights"))
    assert update["active_agent"] == "home"
    assert "not configured" in update["tool_results"][0].lower()


@pytest.mark.asyncio
async def test_home_node_call_service():
    from agents.home import home_node
    update_config(hass_url="http://ha.local:8123", hass_token="tok")

    with patch("agents.home.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.home.call_service", new_callable=AsyncMock) as mock_svc:
        mock_llm.return_value = {
            "content": '{"op":"call_service","domain":"light","service":"turn_on","entity_id":"light.kitchen"}'
        }
        mock_svc.return_value = "Called light.turn_on — affected: light.kitchen"
        update = await home_node(_state("turn on the kitchen light"))

    assert update["active_agent"] == "home"
    mock_svc.assert_awaited_once_with(
        "http://ha.local:8123", "tok", "light", "turn_on", "light.kitchen"
    )
    assert "light.turn_on" in update["tool_results"][0]


@pytest.mark.asyncio
async def test_home_node_get_state():
    from agents.home import home_node
    update_config(hass_url="http://ha.local:8123", hass_token="tok")

    with patch("agents.home.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.home.get_state", new_callable=AsyncMock) as mock_gs:
        mock_llm.return_value = {
            "content": '{"op":"get_state","entity_id":"sensor.temp"}'
        }
        mock_gs.return_value = "Living Room Temp: 21.5 °C"
        update = await home_node(_state("what's the temperature"))

    assert "21.5" in update["tool_results"][0]
    mock_gs.assert_awaited_once_with("http://ha.local:8123", "tok", "sensor.temp")


@pytest.mark.asyncio
async def test_home_node_list_states():
    from agents.home import home_node
    update_config(hass_url="http://ha.local:8123", hass_token="tok")

    with patch("agents.home.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.home.list_states", new_callable=AsyncMock) as mock_ls:
        mock_llm.return_value = {"content": '{"op":"list_states","domain":"light"}'}
        mock_ls.return_value = "  Kitchen (light.kitchen): on"
        update = await home_node(_state("list all lights"))

    mock_ls.assert_awaited_once_with("http://ha.local:8123", "tok", "light")
    assert "Kitchen" in update["tool_results"][0]


@pytest.mark.asyncio
async def test_home_node_llm_parse_failure_returns_error():
    from agents.home import home_node
    update_config(hass_url="http://ha.local:8123", hass_token="tok")

    with patch("agents.home.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("llm down")
        update = await home_node(_state("turn on lights"))

    assert update["active_agent"] == "home"
    assert "failed" in update["tool_results"][0].lower()


@pytest.mark.asyncio
async def test_home_node_ha_error_returns_error_string():
    from agents.home import home_node
    update_config(hass_url="http://ha.local:8123", hass_token="tok")

    with patch("agents.home.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.home.call_service", new_callable=AsyncMock) as mock_svc:
        mock_llm.return_value = {
            "content": '{"op":"call_service","domain":"light","service":"turn_on","entity_id":"light.x"}'
        }
        mock_svc.side_effect = Exception("connection refused")
        update = await home_node(_state("turn on light x"))

    assert "error" in update["tool_results"][0].lower()
