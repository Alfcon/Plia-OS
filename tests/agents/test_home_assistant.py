import pytest
import httpx
import respx
from agents.home_assistant import call_service, get_state, list_states

BASE = "http://homeassistant.local:8123"
TOKEN = "test_token"


@respx.mock
@pytest.mark.asyncio
async def test_call_service_success():
    respx.post(f"{BASE}/api/services/light/turn_on").mock(
        return_value=httpx.Response(200, json=[{"entity_id": "light.kitchen"}])
    )
    result = await call_service(BASE, TOKEN, "light", "turn_on", "light.kitchen")
    assert "light.turn_on" in result
    assert "light.kitchen" in result


@respx.mock
@pytest.mark.asyncio
async def test_call_service_entity_not_found():
    respx.post(f"{BASE}/api/services/light/turn_on").mock(
        return_value=httpx.Response(404)
    )
    result = await call_service(BASE, TOKEN, "light", "turn_on", "light.nonexistent")
    assert "not found" in result.lower()


@respx.mock
@pytest.mark.asyncio
async def test_call_service_no_entity_id():
    respx.post(f"{BASE}/api/services/light/turn_off").mock(
        return_value=httpx.Response(200, json=[])
    )
    result = await call_service(BASE, TOKEN, "light", "turn_off")
    assert "light.turn_off" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_state_success():
    respx.get(f"{BASE}/api/states/sensor.temp").mock(
        return_value=httpx.Response(200, json={
            "entity_id": "sensor.temp",
            "state": "21.5",
            "attributes": {"friendly_name": "Living Room Temp", "unit_of_measurement": "°C"},
        })
    )
    result = await get_state(BASE, TOKEN, "sensor.temp")
    assert "Living Room Temp" in result
    assert "21.5" in result
    assert "°C" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_state_not_found():
    respx.get(f"{BASE}/api/states/sensor.missing").mock(
        return_value=httpx.Response(404)
    )
    result = await get_state(BASE, TOKEN, "sensor.missing")
    assert "not found" in result.lower()


@respx.mock
@pytest.mark.asyncio
async def test_list_states_no_domain_filter():
    respx.get(f"{BASE}/api/states").mock(
        return_value=httpx.Response(200, json=[
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen"}},
            {"entity_id": "switch.fan", "state": "off", "attributes": {"friendly_name": "Fan"}},
        ])
    )
    result = await list_states(BASE, TOKEN)
    assert "Kitchen" in result
    assert "Fan" in result


@respx.mock
@pytest.mark.asyncio
async def test_list_states_with_domain_filter():
    respx.get(f"{BASE}/api/states").mock(
        return_value=httpx.Response(200, json=[
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            {"entity_id": "switch.fan", "state": "off", "attributes": {}},
        ])
    )
    result = await list_states(BASE, TOKEN, domain="light")
    assert "light.kitchen" in result
    assert "switch.fan" not in result


@respx.mock
@pytest.mark.asyncio
async def test_list_states_empty():
    respx.get(f"{BASE}/api/states").mock(
        return_value=httpx.Response(200, json=[])
    )
    result = await list_states(BASE, TOKEN)
    assert "no entities" in result.lower()
