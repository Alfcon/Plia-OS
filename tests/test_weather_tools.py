import pytest
import httpx
from unittest.mock import patch, MagicMock

_GEO_RESULT = {
    "results": [{"name": "Berlin", "latitude": 52.52, "longitude": 13.41, "country": "Germany"}]
}
_GEO_EMPTY = {"results": []}

_CURRENT_DATA = {
    "current": {
        "temperature_2m": 18.0,
        "apparent_temperature": 15.0,
        "relative_humidity_2m": 67,
        "wind_speed_10m": 14.0,
        "weathercode": 2,
    }
}

_FORECAST_DATA = {
    "daily": {
        "time": ["2026-06-19", "2026-06-20", "2026-06-21"],
        "temperature_2m_max": [20.0, 15.0, 18.0],
        "temperature_2m_min": [11.0, 9.0, 12.0],
        "precipitation_probability_max": [10, 80, 30],
        "weathercode": [2, 63, 1],
    }
}

_UV_DATA = {"hourly": {"uv_index": [6.0] * 24}}


def _mock(json_data):
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = json_data
    return m


def test_current_weather_success():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_CURRENT_DATA)]):
        result = get_current_weather("Berlin")
    assert "Berlin" in result
    assert "18.0" in result
    assert "⛅" in result or "partly cloudy" in result.lower()


def test_current_weather_uses_config_location():
    from modules.weather_tools import get_current_weather
    mock_cfg = MagicMock()
    mock_cfg.weather_location = "Berlin"
    with patch("modules.weather_tools.get_config", return_value=mock_cfg), \
         patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_CURRENT_DATA)]):
        result = get_current_weather("")
    assert "Berlin" in result


def test_current_weather_no_location_set():
    from modules.weather_tools import get_current_weather
    mock_cfg = MagicMock()
    mock_cfg.weather_location = ""
    with patch("modules.weather_tools.get_config", return_value=mock_cfg):
        result = get_current_weather("")
    assert "Settings" in result or "location" in result.lower()


def test_current_weather_city_not_found():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get", return_value=_mock(_GEO_EMPTY)):
        result = get_current_weather("Atlantis")
    assert "not found" in result.lower()


def test_current_weather_http_error():
    from modules.weather_tools import get_current_weather
    with patch("modules.weather_tools.httpx.get",
               side_effect=httpx.ConnectError("timeout")):
        result = get_current_weather("Berlin")
    assert "unavailable" in result.lower()


def test_forecast_success():
    from modules.weather_tools import get_forecast
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_FORECAST_DATA)]):
        result = get_forecast("Berlin")
    assert "Berlin" in result
    assert "forecast" in result.lower()
    assert "20.0" in result
    assert "°C / " in result


def test_forecast_fewer_days():
    from modules.weather_tools import get_forecast
    data = {
        "daily": {
            "time": ["2026-06-19", "2026-06-20", "2026-06-21"],
            "temperature_2m_max": [20.0, 15.0, 18.0],
            "temperature_2m_min": [11.0, 9.0, 12.0],
            "precipitation_probability_max": [10, 80, 30],
            "weathercode": [2, 63, 1],
        }
    }
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(data)]):
        result = get_forecast("Berlin", days=3)
    day_lines = [l for l in result.splitlines() if "°C / " in l]
    assert len(day_lines) == 3
    assert "3-day" in result


def test_uv_index_success():
    from modules.weather_tools import get_uv_index
    with patch("modules.weather_tools.httpx.get",
               side_effect=[_mock(_GEO_RESULT), _mock(_UV_DATA)]):
        result = get_uv_index("Berlin")
    assert "Berlin" in result
    assert "6" in result
    assert "High" in result


def test_uv_index_categories():
    from modules.weather_tools import _uv_label
    assert _uv_label(0) == "Low"
    assert _uv_label(2.9) == "Low"
    assert _uv_label(3) == "Moderate"
    assert _uv_label(6) == "High"
    assert _uv_label(8) == "Very High"
    assert _uv_label(11) == "Extreme"


def test_wmo_unknown_code():
    from modules.weather_tools import _wmo
    result = _wmo(999)
    assert "999" in result
