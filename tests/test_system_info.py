from contextlib import ExitStack
from unittest.mock import patch, MagicMock


def _mock_psutil(cpu=42.5, cpu_count=8, ram_used=4, ram_total=16, ram_percent=25.0,
                 disk_used=100, disk_total=500, disk_percent=20.0):
    mem = MagicMock()
    mem.used = ram_used * 1024 ** 3
    mem.total = ram_total * 1024 ** 3
    mem.percent = ram_percent

    disk = MagicMock()
    disk.used = disk_used * 1024 ** 3
    disk.total = disk_total * 1024 ** 3
    disk.percent = disk_percent

    return mem, disk, cpu, cpu_count


def _stack(mem, disk, cpu, cpu_count, gpu_name=None, gpu_vram=0.0):
    s = ExitStack()
    s.enter_context(patch("psutil.cpu_percent", return_value=cpu))
    s.enter_context(patch("psutil.cpu_count", return_value=cpu_count))
    s.enter_context(patch("psutil.virtual_memory", return_value=mem))
    s.enter_context(patch("psutil.disk_usage", return_value=disk))
    s.enter_context(patch("core.system_fit.get_gpu_name", return_value=gpu_name))
    s.enter_context(patch("core.system_fit.get_gpu_vram_gb", return_value=gpu_vram))
    return s


def test_get_system_info_shows_cpu():
    mem, disk, cpu, cpu_count = _mock_psutil(cpu=55.2, cpu_count=4)
    with _stack(mem, disk, cpu, cpu_count):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "55.2%" in result
    assert "CPU" in result
    assert "4 cores" in result


def test_get_system_info_shows_ram():
    mem, disk, cpu, cpu_count = _mock_psutil(ram_used=8, ram_total=32, ram_percent=25.0)
    with _stack(mem, disk, cpu, cpu_count):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "8.0/32.0 GB" in result
    assert "RAM" in result


def test_get_system_info_shows_disk():
    mem, disk, cpu, cpu_count = _mock_psutil(disk_used=200, disk_total=1000, disk_percent=20.0)
    with _stack(mem, disk, cpu, cpu_count):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "200.0/1000.0 GB" in result
    assert "Disk" in result


def test_get_system_info_shows_gpu_when_present():
    mem, disk, cpu, cpu_count = _mock_psutil()
    with _stack(mem, disk, cpu, cpu_count, gpu_name="RTX 3080", gpu_vram=10.0):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "RTX 3080" in result
    assert "10.0 GB VRAM" in result


def test_get_system_info_omits_gpu_when_absent():
    mem, disk, cpu, cpu_count = _mock_psutil()
    with _stack(mem, disk, cpu, cpu_count, gpu_name=None, gpu_vram=0.0):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "GPU" not in result


def test_get_system_info_integration():
    from modules.example_module import get_system_info
    result = get_system_info()
    assert "CPU" in result
    assert "RAM" in result
    assert "Disk" in result
    assert "%" in result
