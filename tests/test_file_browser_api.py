from __future__ import annotations
import os
import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_list_dir(tmp_path):
    (tmp_path / "subdir").mkdir()
    (tmp_path / "file.txt").write_text("hello")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files", params={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(tmp_path)
    names = {e["name"] for e in data["entries"]}
    assert "subdir" in names
    assert "file.txt" in names


@pytest.mark.asyncio
async def test_list_dir_sorted_dirs_first(tmp_path):
    (tmp_path / "z_file.txt").write_text("")
    (tmp_path / "a_dir").mkdir()
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files", params={"path": str(tmp_path)})
    entries = r.json()["entries"]
    assert entries[0]["type"] == "dir"
    assert entries[1]["type"] == "file"


@pytest.mark.asyncio
async def test_list_dir_not_found(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files", params={"path": str(tmp_path / "nonexistent")})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_read_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("world")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files/read", params={"path": str(f)})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "world"
    assert data["binary"] is False
    assert data["size"] == 5


@pytest.mark.asyncio
async def test_read_binary_file(tmp_path):
    f = tmp_path / "bin.bin"
    f.write_bytes(bytes(range(256)))
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files/read", params={"path": str(f)})
    assert r.status_code == 200
    data = r.json()
    assert data["binary"] is True
    assert data["content"] == ""


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/files/read", params={"path": str(tmp_path / "missing.txt")})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_write_file(tmp_path):
    path = str(tmp_path / "new.txt")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/write", json={"path": path, "content": "created"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert (tmp_path / "new.txt").read_text() == "created"


@pytest.mark.asyncio
async def test_write_file_creates_parents(tmp_path):
    path = str(tmp_path / "deep" / "nested" / "file.txt")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/write", json={"path": path, "content": "hi"})
    assert r.status_code == 200
    assert (tmp_path / "deep" / "nested" / "file.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_write_file_missing_path():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/write", json={"content": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_file(tmp_path):
    f = tmp_path / "todel.txt"
    f.write_text("bye")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/files", params={"path": str(f)})
    assert r.status_code == 200
    assert not f.exists()


@pytest.mark.asyncio
async def test_delete_directory(tmp_path):
    d = tmp_path / "todeldir"
    d.mkdir()
    (d / "inner.txt").write_text("inner")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/files", params={"path": str(d)})
    assert r.status_code == 200
    assert not d.exists()


@pytest.mark.asyncio
async def test_delete_not_found(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.delete("/api/files", params={"path": str(tmp_path / "ghost.txt")})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_mkdir(tmp_path):
    path = str(tmp_path / "newdir")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/mkdir", json={"path": path})
    assert r.status_code == 200
    assert os.path.isdir(path)


@pytest.mark.asyncio
async def test_mkdir_missing_path():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/mkdir", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_rename_file(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("content")
    dst = str(tmp_path / "new.txt")
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/rename", json={"from": str(src), "to": dst})
    assert r.status_code == 200
    assert not src.exists()
    assert (tmp_path / "new.txt").read_text() == "content"


@pytest.mark.asyncio
async def test_rename_missing_source(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/rename", json={"from": str(tmp_path / "ghost.txt"), "to": str(tmp_path / "x.txt")})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rename_missing_params():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/files/rename", json={"from": "/tmp/x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_files_pick_empty_start_defaults_to_home(tmp_path):
    import subprocess
    from unittest.mock import patch, MagicMock
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(stdout="/picked/path\n")

    with patch("shutil.which", return_value="/usr/bin/zenity"), \
         patch("subprocess.run", side_effect=_fake_run):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/files/pick", json={"mode": "file", "start": ""})

    assert r.status_code == 200
    assert r.json()["path"] == "/picked/path"
    # empty start must resolve to the home dir, not "/"
    filename_arg = next(a for a in captured["cmd"] if a.startswith("--filename="))
    assert filename_arg != "--filename=/"
    assert filename_arg.startswith(f"--filename={os.path.expanduser('~')}")


@pytest.mark.asyncio
async def test_files_pick_subprocess_error_returns_cancelled(tmp_path):
    from unittest.mock import patch

    with patch("shutil.which", return_value="/usr/bin/zenity"), \
         patch("subprocess.run", side_effect=OSError("boom")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/files/pick", json={"mode": "file", "start": "/home/x"})

    assert r.status_code == 200
    assert r.json()["cancelled"] is True


@pytest.mark.asyncio
async def test_files_pick_no_zenity_returns_501(tmp_path):
    from unittest.mock import patch
    with patch("shutil.which", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/files/pick", json={"mode": "file"})
    assert r.status_code == 501
