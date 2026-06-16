import pytest
import httpx
from unittest.mock import patch, MagicMock


def _cfg(url="http://ha.local:8123", token="tok"):
    mock = MagicMock()
    mock.hass_url = url
    mock.hass_token = token
    return mock


def test_toggle_entity_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.post", return_value=mock_resp):
        from modules.example_module import toggle_entity
        result = toggle_entity("light.living_room")
    assert "light.living_room" in result
    assert "Toggled" in result


def test_toggle_entity_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.post", return_value=mock_resp):
        from modules.example_module import toggle_entity
        result = toggle_entity("light.unknown")
    assert "not found" in result.lower()


def test_toggle_entity_not_configured():
    mock_cfg = MagicMock()
    mock_cfg.hass_url = ""
    mock_cfg.hass_token = ""
    with patch("core.config.get_config", return_value=mock_cfg):
        from modules.example_module import toggle_entity
        result = toggle_entity("light.x")
    assert "not configured" in result.lower()


def test_get_entity_state_returns_state():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"entity_id": "light.kitchen", "state": "on"}
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.get", return_value=mock_resp):
        from modules.example_module import get_entity_state
        result = get_entity_state("light.kitchen")
    assert "light.kitchen" in result
    assert "on" in result


def test_list_home_entities_filtered_by_domain():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = [
        {"entity_id": "light.kitchen", "state": "on"},
        {"entity_id": "switch.fan", "state": "off"},
        {"entity_id": "light.bedroom", "state": "off"},
    ]
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.get", return_value=mock_resp):
        from modules.example_module import list_home_entities
        result = list_home_entities(domain="light")
    assert "light.kitchen" in result
    assert "light.bedroom" in result
    assert "switch.fan" not in result


def test_set_brightness_calls_light_turn_on():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.post", return_value=mock_resp) as mock_post:
        from modules.example_module import set_brightness
        result = set_brightness("light.living_room", 50)
    call_json = mock_post.call_args[1]["json"]
    assert call_json["entity_id"] == "light.living_room"
    assert call_json["brightness"] == round(50 * 255 / 100)
    assert "50%" in result


def test_set_brightness_out_of_range():
    with patch("core.config.get_config", return_value=_cfg()):
        from modules.example_module import set_brightness
        assert "0" in set_brightness("light.x", 101) or "100" in set_brightness("light.x", 101)


def test_set_brightness_not_configured():
    mock_cfg = MagicMock()
    mock_cfg.hass_url = ""
    mock_cfg.hass_token = ""
    with patch("core.config.get_config", return_value=mock_cfg):
        from modules.example_module import set_brightness
        result = set_brightness("light.x", 50)
    assert "not configured" in result.lower()


def test_list_home_entities_empty_domain():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = []
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.get", return_value=mock_resp):
        from modules.example_module import list_home_entities
        result = list_home_entities(domain="sensor")
    assert "No entities" in result
