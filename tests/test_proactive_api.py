from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_proactive():
    pro = MagicMock()
    pro.is_running.return_value = False
    pro.last_message_ts.return_value = None
    pro.last_trigger_type.return_value = None
    pro.start = AsyncMock()
    pro.stop = AsyncMock()
    return pro


@pytest.mark.asyncio
async def test_proactive_status_stopped(mock_proactive):
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.get('/api/proactive/status')
    assert r.status_code == 200
    data = r.json()
    assert data['enabled'] is False
    assert data['running'] is False
    assert data['last_message_ts'] is None
    assert data['last_trigger_type'] is None


@pytest.mark.asyncio
async def test_proactive_enable(mock_proactive):
    mock_proactive.is_running.return_value = False
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.post('/api/proactive/enable')
    assert r.status_code == 200
    assert r.json()['success'] is True


@pytest.mark.asyncio
async def test_proactive_disable(mock_proactive):
    mock_proactive.is_running.return_value = True
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.post('/api/proactive/disable')
    assert r.status_code == 200
    assert r.json()['success'] is True


@pytest.mark.asyncio
async def test_proactive_status_config_fields(mock_proactive):
    with patch('core.proactive.get_proactive', return_value=mock_proactive):
        from core.main import create_app
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://test') as client:
            r = await client.get('/api/proactive/status')
    data = r.json()
    assert 'quiet_hours_start' in data
    assert 'quiet_hours_end' in data
    assert 'distraction_threshold' in data
    assert 'checkin_interval' in data
