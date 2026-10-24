from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


_XML = """<?xml version="1.0" ?>
<nvidia_smi_log>
  <gpu>
    <processes>
      <process_info>
        <gpu_instance_id>N/A</gpu_instance_id>
        <compute_instance_id>N/A</compute_instance_id>
        <pid>1379</pid>
        <type>G</type>
        <process_name>/usr/lib/xorg/Xorg</process_name>
        <used_memory>4 MiB</used_memory>
      </process_info>
      <process_info>
        <pid>4242</pid>
        <type>C</type>
        <process_name>python</process_name>
        <used_memory>3198 MiB</used_memory>
      </process_info>
      <process_info>
        <pid>555</pid>
        <type>C</type>
        <process_name>ghost</process_name>
        <used_memory>N/A</used_memory>
      </process_info>
    </processes>
  </gpu>
</nvidia_smi_log>
"""


def _smi_result(stdout: str, returncode: int = 0):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


@pytest.mark.asyncio
async def test_processes_parsed_sorted_and_self_tagged():
    with patch("dashboard.server.subprocess.run", return_value=_smi_result(_XML)), \
         patch("dashboard.server.os.getpid", return_value=4242):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/vram/processes")
    assert r.status_code == 200
    data = r.json()
    assert [p["pid"] for p in data["processes"]] == [4242, 1379, 555]  # sorted by used_mib desc
    python_proc, xorg, ghost = data["processes"]
    assert python_proc == {"pid": 4242, "name": "python", "used_mib": 3198, "is_self": True}
    assert xorg["name"] == "/usr/lib/xorg/Xorg" and xorg["used_mib"] == 4 and xorg["is_self"] is False
    assert ghost["used_mib"] == 0  # "N/A" coerced to 0
    assert data["total_mib"] == 3202


@pytest.mark.asyncio
async def test_processes_no_nvidia_smi_returns_empty_200():
    with patch("dashboard.server.subprocess.run", side_effect=FileNotFoundError):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/vram/processes")
    assert r.status_code == 200
    assert r.json() == {"processes": [], "total_mib": 0}


@pytest.mark.asyncio
async def test_processes_nonzero_exit_returns_empty_200():
    with patch("dashboard.server.subprocess.run", return_value=_smi_result("", returncode=1)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/vram/processes")
    assert r.status_code == 200
    assert r.json() == {"processes": [], "total_mib": 0}


@pytest.mark.asyncio
async def test_processes_garbage_xml_returns_empty_200():
    with patch("dashboard.server.subprocess.run", return_value=_smi_result("not xml at all <")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/vram/processes")
    assert r.status_code == 200
    assert r.json() == {"processes": [], "total_mib": 0}
