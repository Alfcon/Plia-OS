from __future__ import annotations

from unittest.mock import patch

import psutil
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


class _FakeProc:
    """Fake psutil.Process for the two-pass CPU sampler.

    Real psutil 7.2.2: process_iter(attrs=...) computes .info eagerly and
    never yields dead processes. But *method* calls on a yielded Process
    (cpu_percent) can raise NoSuchProcess etc. if the process exits after
    being yielded. First cpu_percent(None) call returns 0.0 (prime);
    second returns core-relative % over the window. dies_mid_window
    simulates exit between prime and read: second call raises.
    """

    def __init__(self, pid, name, pct, dies_mid_window=False):
        self.info = {"pid": pid, "name": name}
        self._pct = pct
        self._dies = dies_mid_window
        self._primed = False

    def cpu_percent(self, interval=None):
        if not self._primed:
            self._primed = True
            return 0.0
        if self._dies:
            raise psutil.NoSuchProcess(self.info["pid"])
        return self._pct


def _fake_procs():
    procs = [
        _FakeProc(4242, "python", 320.0),                    # is_self; 320/8 = 40.0
        _FakeProc(100, "firefox", 42.0),
        _FakeProc(101, "firefox", 42.0),                     # 84/8 = 10.5, count 2
        _FakeProc(102, "firefox", 999.0, dies_mid_window=True),  # dies → skipped, not counted
    ]
    # 12 distinct groups to force a top-10 cutoff: svc00 = 96/8 = 12.0 … svc11 = 8/8 = 1.0
    procs += [_FakeProc(200 + i, f"svc{i:02d}", (12 - i) * 8.0) for i in range(12)]
    return procs


@pytest.mark.asyncio
async def test_grouping_normalization_cutoff_and_self():
    with patch("dashboard.server.psutil.process_iter", return_value=_fake_procs()), \
         patch("dashboard.server.psutil.cpu_count", return_value=8), \
         patch("dashboard.server.psutil.cpu_percent", return_value=23.5), \
         patch("dashboard.server.time.sleep"), \
         patch("dashboard.server.os.getpid", return_value=4242):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cpu/processes")
    assert r.status_code == 200
    data = r.json()

    assert len(data["processes"]) == 10
    top = data["processes"][0]
    assert top == {"name": "python", "count": 1, "cpu_percent": 40.0, "is_self": True}
    # firefox: two survivors summed (42+42=84 core-% → 10.5 system-%); the
    # process that died mid-window is skipped entirely, so count is 2 not 3
    firefox = next(p for p in data["processes"] if p["name"] == "firefox")
    assert firefox == {"name": "firefox", "count": 2, "cpu_percent": 10.5, "is_self": False}
    # rows sorted desc by cpu_percent
    pcts = [p["cpu_percent"] for p in data["processes"]]
    assert pcts == sorted(pcts, reverse=True)
    # 14 groups (python, firefox, svc00..svc11) → 4 beyond top 10:
    # svc08..svc11 = 4.0+3.0+2.0+1.0 system-%
    assert data["more_count"] == 4
    assert data["more_percent"] == 10.0
    assert data["total_percent"] == 23.5


@pytest.mark.asyncio
async def test_top_level_failure_returns_zeroed_200():
    with patch("dashboard.server.psutil.process_iter", side_effect=RuntimeError("boom")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/cpu/processes")
    assert r.status_code == 200
    assert r.json() == {
        "processes": [], "more_count": 0, "more_percent": 0.0, "total_percent": 0.0,
    }
