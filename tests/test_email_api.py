from __future__ import annotations
import contextlib
import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


@pytest.fixture(autouse=True)
def _iso(isolate_email_store):
    pass


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_email_test_endpoint_imap_success():
    mock_mb = MagicMock()
    mock_mb.folder.status.return_value = {"UNSEEN": 2}

    @contextlib.contextmanager
    def _fake_conn(acc):
        yield mock_mb

    from agents.email_store import add_account
    add_account({"name": "Work", "provider": "imap", "username": "u", "password": "p",
                 "imap_host": "imap.example.com"})

    with patch("agents.email_client.imap_connection", side_effect=_fake_conn):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/email/accounts/Work/test")

    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "unread" in d["message"].lower() or "connected" in d["message"].lower()


@pytest.mark.asyncio
async def test_email_test_endpoint_imap_failure():
    @contextlib.contextmanager
    def _bad_conn(acc):
        raise ConnectionRefusedError("Connection refused")
        yield  # make it a generator

    from agents.email_store import add_account
    add_account({"name": "Fail", "provider": "imap", "username": "u", "password": "wrong",
                 "imap_host": "imap.example.com"})

    with patch("agents.email_client.imap_connection", side_effect=_bad_conn):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/email/accounts/Fail/test")

    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert "Connection refused" in d["message"]


@pytest.mark.asyncio
async def test_email_test_endpoint_not_found():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/email/accounts/NoSuch/test")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_email_list_strips_password():
    from agents.email_store import add_account
    add_account({"name": "Work", "provider": "imap", "username": "u", "password": "secret"})
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/email/accounts")
    assert r.status_code == 200
    accounts = r.json()
    assert len(accounts) == 1
    assert "password" not in accounts[0]
    assert accounts[0]["username"] == "u"


@pytest.mark.asyncio
async def test_email_add_and_remove():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/email/accounts",
                         json={"name": "Test", "provider": "imap", "username": "u"})
        assert r.status_code == 200

        r2 = await c.get("/api/email/accounts")
        assert len(r2.json()) == 1

        r3 = await c.delete("/api/email/accounts/Test")
        assert r3.status_code == 200

        r4 = await c.get("/api/email/accounts")
        assert r4.json() == []
