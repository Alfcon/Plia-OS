import pytest
from unittest.mock import AsyncMock, patch
from agents.weather import weather_node


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
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await weather_node(_state("what's the weather"))
    assert update["active_agent"] == "weather"
    result = "\n".join(update["tool_results"])
    assert result.startswith("[weather]")


@pytest.mark.asyncio
async def test_unknown_action_returns_fallback():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"action":"unknown","location":""}'}
        update = await weather_node(_state("what's the weather"))
    assert update["active_agent"] == "weather"
    result = "\n".join(update["tool_results"])
    assert "couldn't parse" in result.lower()


@pytest.mark.asyncio
async def test_action_current_calls_get_current_weather():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_current_weather",
               return_value="Berlin: ⛅ 18°C") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"current","location":"Berlin"}'}
        update = await weather_node(_state("weather in Berlin"))
    mock_fn.assert_called_once_with("Berlin")
    assert update["active_agent"] == "weather"
    assert any(r.startswith("[weather]") for r in update["tool_results"])
    assert "Berlin" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_action_forecast_calls_get_forecast():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_forecast",
               return_value="7-day forecast for Tokyo:") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"forecast","location":"Tokyo"}'}
        update = await weather_node(_state("forecast for Tokyo"))
    mock_fn.assert_called_once_with("Tokyo")
    assert update["active_agent"] == "weather"


@pytest.mark.asyncio
async def test_action_uv_calls_get_uv_index():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_uv_index",
               return_value="Berlin UV index: 6 (High)") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"uv","location":"Berlin"}'}
        update = await weather_node(_state("uv index in Berlin"))
    mock_fn.assert_called_once_with("Berlin")
    assert update["active_agent"] == "weather"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.weather.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.weather.get_current_weather", return_value="Berlin: ⛅ 18°C"):
        mock_llm.return_value = {"content": '{"action":"current","location":""}'}
        state = _state("weather")
        state["tool_results"] = ["[memory]\nprior context"]
        update = await weather_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nprior context"
