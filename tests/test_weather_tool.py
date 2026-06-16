from unittest.mock import patch, MagicMock
import httpx


def _mock_resp(text, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    mock.raise_for_status = MagicMock()
    return mock


def test_get_weather_returns_text():
    with patch("httpx.get", return_value=_mock_resp("London: ⛅️ +15°C")):
        from modules.example_module import get_weather
        result = get_weather("London")
    assert "London" in result
    assert "15" in result


def test_get_weather_default_location():
    with patch("httpx.get", return_value=_mock_resp("Paris: ☀️ +22°C")) as mock_get:
        from modules.example_module import get_weather
        get_weather("here")
    url = mock_get.call_args[0][0]
    assert "wttr.in/" in url
    assert "here" not in url


def test_get_weather_named_location():
    with patch("httpx.get", return_value=_mock_resp("Tokyo: 🌧 +18°C")) as mock_get:
        from modules.example_module import get_weather
        get_weather("Tokyo")
    url = mock_get.call_args[0][0]
    assert "Tokyo" in url


def test_get_weather_http_error():
    with patch("httpx.get", side_effect=httpx.ConnectError("timeout")):
        from modules.example_module import get_weather
        result = get_weather("London")
    assert "failed" in result.lower()
