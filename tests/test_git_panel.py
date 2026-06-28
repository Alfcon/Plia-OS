from __future__ import annotations
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_git(returncode=0, stdout="", stderr=""):
    async def _fake_git(*args, **kwargs):
        return returncode, stdout, stderr
    return _fake_git


# ── Unit: _parse_status ───────────────────────────────────────────────────────

def test_parse_status_staged_modified():
    from dashboard.server import _parse_status
    result = _parse_status("M  src/foo.py\n")
    assert result["staged"] == [{"status": "modified", "path": "src/foo.py"}]
    assert result["unstaged"] == []


def test_parse_status_unstaged_modified():
    from dashboard.server import _parse_status
    result = _parse_status(" M src/bar.py\n")
    assert result["unstaged"] == [{"status": "modified", "path": "src/bar.py"}]
    assert result["staged"] == []


def test_parse_status_untracked():
    from dashboard.server import _parse_status
    result = _parse_status("?? new_file.py\n")
    assert "new_file.py" in result["untracked"]
    assert result["staged"] == []


def test_parse_status_added():
    from dashboard.server import _parse_status
    result = _parse_status("A  newfile.py\n")
    assert result["staged"][0]["status"] == "added"


def test_parse_status_deleted():
    from dashboard.server import _parse_status
    result = _parse_status(" D removed.py\n")
    assert result["unstaged"][0]["status"] == "deleted"


def test_parse_status_empty():
    from dashboard.server import _parse_status
    result = _parse_status("")
    assert result == {"staged": [], "unstaged": [], "untracked": []}


# ── API tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_git_status_ok():
    with patch("dashboard.server._git", side_effect=[
        (0, "main\n", ""),
        (0, "M  foo.py\n", ""),
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/git/status")
    assert r.status_code == 200
    data = r.json()
    assert data["branch"] == "main"
    assert data["clean"] is False
    assert data["staged"][0]["path"] == "foo.py"


@pytest.mark.asyncio
async def test_git_status_clean():
    with patch("dashboard.server._git", side_effect=[
        (0, "main\n", ""),
        (0, "", ""),
    ]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/git/status")
    assert r.json()["clean"] is True


@pytest.mark.asyncio
async def test_git_status_not_repo():
    with patch("dashboard.server._git", side_effect=[(1, "", "fatal: not a git repository")]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/git/status")
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_git_log():
    log_line = "abc1234def5678|2026-06-28 09:00:00 +0000|Alice|feat: add thing"
    with patch("dashboard.server._git", return_value=(0, log_line + "\n", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/git/log")
    assert r.status_code == 200
    commits = r.json()["commits"]
    assert len(commits) == 1
    assert commits[0]["short"] == "abc1234"
    assert commits[0]["author"] == "Alice"
    assert commits[0]["message"] == "feat: add thing"


@pytest.mark.asyncio
async def test_git_diff_unstaged():
    diff = "diff --git a/foo.py b/foo.py\n+added line\n-removed line\n"
    with patch("dashboard.server._git", return_value=(0, diff, "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/git/diff?path=foo.py&staged=false")
    assert r.status_code == 200
    assert "+added line" in r.json()["diff"]


@pytest.mark.asyncio
async def test_git_stage_files():
    with patch("dashboard.server._git", return_value=(0, "", "")) as mock_git:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/stage", json={"files": ["foo.py"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_git_stage_all():
    with patch("dashboard.server._git", return_value=(0, "", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/stage", json={"all": True})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_git_stage_missing_params():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/git/stage", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_git_unstage():
    with patch("dashboard.server._git", return_value=(0, "", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/unstage", json={"files": ["foo.py"]})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_git_unstage_missing_files():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/git/unstage", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_git_commit_ok():
    with patch("dashboard.server._git", return_value=(0, "[main abc1234] feat: thing", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/commit", json={"message": "feat: thing"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_git_commit_empty_message():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/git/commit", json={"message": "  "})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_git_commit_failure():
    with patch("dashboard.server._git", return_value=(1, "", "nothing to commit")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/commit", json={"message": "oops"})
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_git_push_ok():
    with patch("dashboard.server._git", return_value=(0, "Everything up-to-date", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/push")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_git_push_failure():
    with patch("dashboard.server._git", return_value=(1, "", "remote: error")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/push")
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_git_pull_ok():
    with patch("dashboard.server._git", return_value=(0, "Already up to date.", "")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/git/pull")
    assert r.status_code == 200
    assert "up to date" in r.json()["output"].lower()
