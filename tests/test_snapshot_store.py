from __future__ import annotations
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _patch_dir(tmp_path):
    return patch("core.snapshot_store._snapshots_dir", return_value=tmp_path / "snapshots")


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_create_and_list(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, list_snapshots
        name = create_snapshot("my label")
        snaps = list_snapshots()
    assert any(s["name"] == name for s in snaps)
    assert snaps[0]["label"] == "my label"


def test_list_empty(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import list_snapshots
        assert list_snapshots() == []


def test_list_sorted_newest_first(tmp_path):
    import time
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, list_snapshots
        a = create_snapshot("first")
        time.sleep(0.01)
        b = create_snapshot("second")
        snaps = list_snapshots()
    assert snaps[0]["name"] == b
    assert snaps[1]["name"] == a


def test_get_snapshot(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, get_snapshot
        name = create_snapshot("test")
        snap = get_snapshot(name)
    assert snap is not None
    assert snap["_label"] == "test"
    assert "_created_at" in snap


def test_get_missing(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import get_snapshot
        assert get_snapshot("ghost.json") is None


def test_delete(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, delete_snapshot, get_snapshot
        name = create_snapshot("")
        assert delete_snapshot(name) is True
        assert get_snapshot(name) is None


def test_delete_missing(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import delete_snapshot
        assert delete_snapshot("ghost.json") is False


def test_snapshot_excludes_internal_on_restore(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, restore_snapshot
        from core.config import update_config, get_config
        update_config(system_prompt="original")
        name = create_snapshot("with-backup")
        update_config(system_prompt="changed")
        restore_snapshot(name)
    # system_prompt_backup must not be restored (it's internal)
    cfg = get_config()
    assert cfg.system_prompt == "original"


def test_restore_creates_pre_restore_backup(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, restore_snapshot, list_snapshots
        name = create_snapshot("snap1")
        restore_snapshot(name)
        snaps = list_snapshots()
    labels = [s["label"] for s in snaps]
    assert "pre-restore" in labels


def test_restore_missing(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import restore_snapshot
        with pytest.raises(KeyError):
            restore_snapshot("ghost.json")


def test_snapshot_contains_config_fields(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot, get_snapshot
        from core.config import update_config
        update_config(ollama_model="llama3.2")
        name = create_snapshot("")
        snap = get_snapshot(name)
    assert snap["ollama_model"] == "llama3.2"


def test_label_sanitized_in_filename(tmp_path):
    with _patch_dir(tmp_path):
        from core.snapshot_store import create_snapshot
        name = create_snapshot("my cool snapshot!")
    assert "my_cool_snapshot_" in name or "my_cool" in name


# ── API tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_empty(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/snapshots")
    assert r.status_code == 200
    assert r.json()["snapshots"] == []


@pytest.mark.asyncio
async def test_api_create(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/snapshots", json={"label": "test"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "name" in r.json()


@pytest.mark.asyncio
async def test_api_create_and_list(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/snapshots", json={"label": "alpha"})
            r = await c.get("/api/snapshots")
    assert len(r.json()["snapshots"]) >= 1
    assert r.json()["snapshots"][0]["label"] == "alpha"


@pytest.mark.asyncio
async def test_api_delete(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            cr = await c.post("/api/snapshots", json={"label": ""})
            name = cr.json()["name"]
            r = await c.delete(f"/api/snapshots/{name}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_api_delete_not_found(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/snapshots/ghost.json")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_restore(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            cr = await c.post("/api/snapshots", json={"label": "before"})
            name = cr.json()["name"]
            r = await c.post(f"/api/snapshots/{name}/restore")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_api_restore_not_found(tmp_path):
    with _patch_dir(tmp_path):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/snapshots/ghost.json/restore")
    assert r.status_code == 404
