from __future__ import annotations
import logging
import pytest
from core.log_buffer import LogBuffer, install, get_log_buffer


def _fresh_buf(capacity=100):
    return LogBuffer(capacity=capacity)


def test_buffer_stores_records():
    buf = _fresh_buf()
    root = logging.getLogger("test_log_buf_store")
    root.addHandler(buf)
    root.setLevel(logging.DEBUG)
    root.info("hello world")
    records = buf.get(n=10)
    assert any("hello world" in r["msg"] for r in records)
    root.removeHandler(buf)


def test_buffer_level_filter():
    buf = _fresh_buf()
    logger = logging.getLogger("test_log_buf_level")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.debug("debug msg")
    logger.info("info msg")
    logger.warning("warn msg")
    records = buf.get(n=100, min_level=logging.WARNING)
    levels = {r["level"] for r in records}
    assert "WARNING" in levels
    assert "DEBUG" not in levels
    assert "INFO" not in levels
    logger.removeHandler(buf)


def test_buffer_capacity_ring():
    buf = _fresh_buf(capacity=5)
    logger = logging.getLogger("test_log_buf_cap")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    for i in range(10):
        logger.info("msg %d", i)
    records = buf.get(n=100)
    assert len(records) <= 5
    msgs = [r["msg"] for r in records]
    assert any("msg 9" in m for m in msgs)
    assert not any("msg 0" in m for m in msgs)
    logger.removeHandler(buf)


def test_buffer_clear():
    buf = _fresh_buf()
    logger = logging.getLogger("test_log_buf_clear")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.info("before clear")
    buf.clear()
    assert buf.get() == []
    logger.removeHandler(buf)


def test_buffer_n_limit():
    buf = _fresh_buf()
    logger = logging.getLogger("test_log_buf_n")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    for i in range(20):
        logger.info("item %d", i)
    records = buf.get(n=5)
    assert len(records) == 5
    logger.removeHandler(buf)


def test_record_fields():
    buf = _fresh_buf()
    logger = logging.getLogger("test_log_buf_fields")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.warning("check fields")
    records = buf.get()
    r = next(x for x in records if "check fields" in x["msg"])
    assert r["level"] == "WARNING"
    assert r["levelno"] == logging.WARNING
    assert "test_log_buf_fields" in r["name"]
    assert isinstance(r["ts"], float)
    logger.removeHandler(buf)


def test_install_idempotent():
    install()
    install()
    buf = get_log_buffer()
    root = logging.getLogger()
    count = sum(1 for h in root.handlers if isinstance(h, LogBuffer))
    assert count == 1


@pytest.mark.asyncio
async def test_api_get_logs():
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from core.main import create_app
    install()
    logging.getLogger("test_api_logs").info("api test record")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/api/logs", params={"n": 500, "level": "DEBUG"})
    assert r.status_code == 200
    data = r.json()
    assert "records" in data
    assert isinstance(data["records"], list)


@pytest.mark.asyncio
async def test_api_get_logs_level_filter():
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from core.main import create_app
    install()
    logging.getLogger("test_api_logs_level").warning("filter test warning")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/api/logs", params={"n": 500, "level": "WARNING"})
    assert r.status_code == 200
    records = r.json()["records"]
    for rec in records:
        assert rec["levelno"] >= logging.WARNING


@pytest.mark.asyncio
async def test_api_clear_logs():
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport
    from core.main import create_app
    install()
    logging.getLogger("test_api_clear").info("to be cleared")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.post("/api/logs/clear")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    buf = get_log_buffer()
    assert buf.get() == []
