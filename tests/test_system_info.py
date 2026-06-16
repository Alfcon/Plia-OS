from unittest.mock import patch, MagicMock


def _mock_psutil(cpu=42.5, ram_used=4, ram_total=16, ram_percent=25.0,
                 disk_used=100, disk_total=500, disk_percent=20.0):
    mem = MagicMock()
    mem.used = ram_used * 1024 ** 3
    mem.total = ram_total * 1024 ** 3
    mem.percent = ram_percent

    disk = MagicMock()
    disk.used = disk_used * 1024 ** 3
    disk.total = disk_total * 1024 ** 3
    disk.percent = disk_percent

    return mem, disk, cpu


def test_get_system_info_shows_cpu():
    mem, disk, cpu = _mock_psutil(cpu=55.2)
    with patch("psutil.cpu_percent", return_value=cpu), \
         patch("psutil.virtual_memory", return_value=mem), \
         patch("psutil.disk_usage", return_value=disk):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "55.2%" in result
    assert "CPU" in result


def test_get_system_info_shows_ram():
    mem, disk, cpu = _mock_psutil(ram_used=8, ram_total=32, ram_percent=25.0)
    with patch("psutil.cpu_percent", return_value=cpu), \
         patch("psutil.virtual_memory", return_value=mem), \
         patch("psutil.disk_usage", return_value=disk):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "8.0/32.0 GB" in result
    assert "RAM" in result


def test_get_system_info_shows_disk():
    mem, disk, cpu = _mock_psutil(disk_used=200, disk_total=1000, disk_percent=20.0)
    with patch("psutil.cpu_percent", return_value=cpu), \
         patch("psutil.virtual_memory", return_value=mem), \
         patch("psutil.disk_usage", return_value=disk):
        from modules.example_module import get_system_info
        result = get_system_info()
    assert "200.0/1000.0 GB" in result
    assert "Disk" in result


def test_get_system_info_integration():
    from modules.example_module import get_system_info
    result = get_system_info()
    assert "CPU" in result
    assert "RAM" in result
    assert "Disk" in result
    assert "%" in result
