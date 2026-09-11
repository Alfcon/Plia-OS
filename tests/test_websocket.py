import json
import asyncio
import pytest
from starlette.testclient import TestClient
from core.main import create_app
from core import events
import dashboard.server as _srv


@pytest.fixture(autouse=True)
def reset_ws_state():
    _srv._ws_clients.clear()
    _srv._recent_notifications.clear()
    yield
    _srv._ws_clients.clear()
    _srv._recent_notifications.clear()


def _emit(event_type, **data):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(events.emit(event_type, data))
    finally:
        loop.close()


def _client():
    app = create_app()
    return TestClient(app)


def _recv_type(ws, expected_type, max_msgs=25):
    """Read messages until one matches expected_type; skip replayed events."""
    for _ in range(max_msgs):
        data = json.loads(ws.receive_text())
        if data.get("type") == expected_type:
            return data
    raise AssertionError(f"never received event type '{expected_type}'")


def test_websocket_connects_and_receives_broadcast():
    with _client() as client:
        with client.websocket_connect("/ws") as ws:
            _emit("transcript", role="assistant", text="hello")
            data = _recv_type(ws, "transcript")
    assert data["text"] == "hello"


def test_websocket_disconnect_removes_client():
    with _client() as client:
        before = len(_srv._ws_clients)
        with client.websocket_connect("/ws"):
            assert len(_srv._ws_clients) == before + 1
        assert len(_srv._ws_clients) == before


def test_websocket_broadcast_reaches_multiple_clients():
    with _client() as client:
        with client.websocket_connect("/ws") as ws1:
            with client.websocket_connect("/ws") as ws2:
                _emit("status", state="armed")
                d1 = _recv_type(ws1, "status")
                d2 = _recv_type(ws2, "status")
    assert d1["state"] == "armed"
    assert d2["state"] == "armed"


def test_websocket_replay_buffer_sends_recent_status_on_connect():
    with _client() as client:
        with client.websocket_connect("/ws") as ws1:
            _emit("status", state="speaking")
            # drain until we see speaking (skip startup armed)
            for _ in range(25):
                d = json.loads(ws1.receive_text())
                if d.get("state") == "speaking":
                    break
        # late-joining client replays buffer; speaking must be present
        with client.websocket_connect("/ws") as ws2:
            found = False
            for _ in range(25):
                d = json.loads(ws2.receive_text())
                if d.get("state") == "speaking":
                    found = True
                    break
    assert found, "replay buffer did not deliver 'speaking' status to late-joining client"


def test_websocket_non_replay_type_not_buffered():
    with _client() as client:
        with client.websocket_connect("/ws") as ws:
            _recv_type(ws, "status")  # drain startup status (replayable)
            before = len(_srv._recent_notifications)
            _emit("transcript", role="user", text="hi")
            _recv_type(ws, "transcript")
    assert len(_srv._recent_notifications) == before
