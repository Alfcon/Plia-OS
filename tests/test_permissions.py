"""Tests for the Permissions panel's backend contract.

A privileged tool only runs when both gates are open: the sudoers grant file
on disk and the tool's level set to "admin".  The API reports both per group,
and the grant commands must target the user running Plia rather than a
hard-coded account.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.config import reset_config
from dashboard import server as dashboard_server
from dashboard.server import (
    _file_granted,
    _grant_state,
    _os_group_payload,
    _plia_sudo_user,
    router,
)


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router)
    yield a
    reset_config()


def _group(tmp_path, *, requires_admin: bool = True, tools=("tool_a", "tool_b")):
    return {
        "id": "test_group",
        "name": "Test Group",
        "description": "test",
        "tools": list(tools),
        "sudoers_file": str(tmp_path / "plia-test"),
        "requires_tool_admin": requires_admin,
        "grant_cmd": "echo '{user} ALL=(ALL) NOPASSWD: true' | sudo tee "
                     + str(tmp_path / "plia-test"),
        "revoke_cmd": "sudo rm " + str(tmp_path / "plia-test"),
    }


def test_grant_command_targets_running_user(tmp_path):
    payload = _os_group_payload(_group(tmp_path), {}, _plia_sudo_user())
    assert f"'{_plia_sudo_user()} ALL=(ALL)" in payload["grant_cmd"]
    assert "{user}" not in payload["grant_cmd"]
    assert "alfcon" not in payload["grant_cmd"] or _plia_sudo_user() == "alfcon"


def test_group_needs_both_grant_and_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_server, "_grant_state", lambda _p: (True, "ok"))
    group = _group(tmp_path)

    only_grant = _os_group_payload(group, {}, "tester")
    assert only_grant["granted"] is True
    assert only_grant["all_admin"] is False
    assert only_grant["ready"] is False

    only_admin = _os_group_payload(
        group, {"tool_a": "admin", "tool_b": "admin"}, "tester")
    assert only_admin["granted"] is True
    assert only_admin["all_admin"] is True
    assert only_admin["ready"] is True

    partial = _os_group_payload(group, {"tool_a": "admin", "tool_b": "user"}, "tester")
    assert partial["admin_count"] == 1
    assert partial["ready"] is False


def test_group_without_tool_gate_is_ready_on_grant_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_server, "_grant_state", lambda _p: (True, "ok"))
    payload = _os_group_payload(_group(tmp_path, requires_admin=False), {}, "tester")
    assert payload["requires_tool_admin"] is False
    assert payload["ready"] is True


def test_world_writable_sudoers_file_is_not_granted(tmp_path):
    f = tmp_path / "plia-test"
    f.write_text("")
    os.chmod(f, 0o666)
    granted, reason = _grant_state(str(f))
    assert granted is False
    assert reason.startswith("insecure mode")
    os.chmod(f, 0o440)
    assert _grant_state(str(f)) == (True, "ok")
    assert _file_granted(str(f)) is True


def test_missing_and_unreadable_grant_reasons(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    assert _grant_state(str(missing)) == (False, "missing")

    def _raise(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(dashboard_server.os, "stat", _raise)
    assert _grant_state(str(missing)) == (False, "unreadable")


async def test_permissions_endpoint_reports_gate_state(app, monkeypatch):
    monkeypatch.setattr(dashboard_server, "_grant_state", lambda _p: (False, "missing"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/permissions")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-store"
    data = resp.json()
    assert data["user"] == _plia_sudo_user()
    assert data["ready_count"] == 0
    by_id = {g["id"]: g for g in data["os_groups"]}
    assert by_id["network_mac"]["requires_tool_admin"] is True
    assert by_id["system_optimise"]["requires_tool_admin"] is False
    assert by_id["network_mac"]["grant_cmd"].startswith(f"echo '{data['user']} ALL=")


async def test_setting_group_tools_to_admin_marks_all_admin(app, monkeypatch):
    from core.registry import tool

    # The endpoint reports levels for *registered* tools, so register the
    # group's tool names in this bare app fixture.
    for name in ("randomize_mac", "set_mac", "restore_mac",
                 "randomize_local_ip", "set_local_ip", "restore_ip"):
        fn = lambda: None
        fn.__name__ = name
        tool("test")(fn)

    monkeypatch.setattr(dashboard_server, "_grant_state", lambda _p: (False, "missing"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        before = (await c.get("/api/permissions")).json()
        mac = next(g for g in before["os_groups"] if g["id"] == "network_mac")
        body = {t: "admin" for t in mac["tools"]}
        resp = await c.post("/api/permissions/tools", json=body)
        assert resp.status_code == 200
        after = (await c.get("/api/permissions")).json()
    mac_after = next(g for g in after["os_groups"] if g["id"] == "network_mac")
    assert mac_after["all_admin"] is True
    assert mac_after["admin_count"] == len(mac["tools"])
    # Grant file still missing, so the group is not ready yet.
    assert mac_after["ready"] is False


async def test_invalid_tool_level_is_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/permissions/tools", json={"show_mac": "root"})
    assert resp.status_code == 422
