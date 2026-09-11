from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_MIB = 1024 * 1024


class _FakeProc:
    """Fake psutil.Process with .info eagerly computed (real psutil semantics).

    Real psutil 7.2.2: process_iter(attrs=...) filters dead procs internally
    (never yielded). Per-attribute access errors inside Process.as_dict()
    (e.g. AccessDenied) are replaced with None via ad_value, not raised.
    This fake mirrors that: plain .info dict with None values for denied attrs.
    """
    def __init__(self, pid, name, rss):
        self.info = {
            "pid": pid,
            "name": name,
            "memory_info": SimpleNamespace(rss=rss) if rss is not None else None,
        }


def _fake_procs():
    procs = [
        _FakeProc(100, "firefox", 700 * _MIB),
        _FakeProc(101, "firefox", 700 * _MIB),      # grouped: firefox ×2 = 1400
        _FakeProc(102, "firefox", None),            # degraded: no memory access → rss=0; firefox ×3 total
        _FakeProc(4242, "python", 2100 * _MIB),     # is_self group
    ]
    # 12 distinct small groups to force a top-10 cutoff
    procs += [_FakeProc(200 + i, f"svc{i:02d}", (12 - i) * _MIB) for i in range(12)]
    return procs


_FAKE_VM = SimpleNamespace(used=5800 * _MIB, total=31000 * _MIB)


@pytest.mark.asyncio
async def test_grouping_sorting_cutoff_and_self():
    with patch("dashboard.server.psutil.process_iter", return_value=_fake_procs()), \
         patch("dashboard.server.psutil.virtual_memory", return_value=_FAKE_VM), \
         patch("dashboard.server.os.getpid", return_value=4242):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/ram/processes")
    assert r.status_code == 200
    data = r.json()

    assert len(data["processes"]) == 10
    top = data["processes"][0]
    assert top == {"name": "python", "count": 1, "rss_mib": 2100, "is_self": True}
    second = data["processes"][1]
    assert second == {"name": "firefox", "count": 3, "rss_mib": 1400, "is_self": False}
    # rows sorted desc by rss_mib
    sizes = [p["rss_mib"] for p in data["processes"]]
    assert sizes == sorted(sizes, reverse=True)
    # 14 groups total (python, firefox, svc00..svc11). firefox ×3 includes one
    # with None memory_info → 4 groups beyond top 10
    assert data["more_count"] == 4
    # svc08..svc11 are the 4 smallest: (12-8)+(12-9)+(12-10)+(12-11) = 4+3+2+1
    assert data["more_mib"] == 10
    assert data["used_mib"] == 5800
    assert data["total_mib"] == 31000


@pytest.mark.asyncio
async def test_top_level_failure_returns_zeroed_200():
    with patch("dashboard.server.psutil.process_iter", side_effect=RuntimeError("boom")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/ram/processes")
    assert r.status_code == 200
    assert r.json() == {
        "processes": [], "more_count": 0, "more_mib": 0, "used_mib": 0, "total_mib": 0,
    }
