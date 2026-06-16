import json
import asyncio
from starlette.testclient import TestClient
from core.main import create_app
from core import events


def _emit(event_type, **data):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(events.emit(event_type, data))
    finally:
        loop.close()


def _client():
    app = create_app()
    return TestClient(app)


def test_websocket_connects_and_receives_broadcast():
    with _client() as client:
        with client.websocket_connect("/ws") as ws:
            _emit("transcript", role="assistant", text="hello")
            data = json.loads(ws.receive_text())
    assert data["type"] == "transcript"
    assert data["text"] == "hello"


def test_websocket_disconnect_removes_client():
    from dashboard.server import _ws_clients
    with _client() as client:
        before = len(_ws_clients)
        with client.websocket_connect("/ws"):
            assert len(_ws_clients) == before + 1
        assert len(_ws_clients) == before


def test_websocket_broadcast_reaches_multiple_clients():
    with _client() as client:
        with client.websocket_connect("/ws") as ws1:
            with client.websocket_connect("/ws") as ws2:
                _emit("status", state="armed")
                d1 = json.loads(ws1.receive_text())
                d2 = json.loads(ws2.receive_text())
    assert d1["state"] == "armed"
    assert d2["state"] == "armed"
