"""The dashboard polls a few read-only endpoints continuously; successful polls
must not flood uvicorn's access log, but failures and real requests still do.
"""
from __future__ import annotations

import logging

from core.main import _QuietPollAccessFilter


def _record(path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", status), None,
    )


def test_successful_polls_are_suppressed():
    f = _QuietPollAccessFilter()
    for path in ("/api/system/info", "/api/permissions", "/api/media/status",
                 "/api/media/volume", "/api/vram/status",
                 "/api/permissions?x=1"):
        assert f.filter(_record(path, 200)) is False
        assert f.filter(_record(path, 304)) is False


def test_failures_on_polls_are_kept():
    f = _QuietPollAccessFilter()
    for status in (400, 404, 500, 503):
        assert f.filter(_record("/api/permissions", status)) is True


def test_normal_requests_are_kept():
    f = _QuietPollAccessFilter()
    for path in ("/api/chat", "/api/tools/run", "/", "/api/permissions/extra"):
        assert f.filter(_record(path, 200)) is True


def test_filter_is_installed_on_uvicorn_access_logger():
    logger = logging.getLogger("uvicorn.access")
    assert any(isinstance(x, _QuietPollAccessFilter) for x in logger.filters)
