from unittest.mock import patch, MagicMock


def _mock_psutil(cpu=25.0, cpu_count=8, ram_used=4.0, ram_total=16.0,
                 ram_pct=25.0, disk_used=100.0, disk_total=500.0, disk_pct=20.0):
    mock = MagicMock()
    mock.cpu_percent.return_value = cpu
    mock.cpu_count.return_value = cpu_count
    vm = MagicMock()
    vm.used = int(ram_used * 1024 ** 3)
    vm.total = int(ram_total * 1024 ** 3)
    vm.percent = ram_pct
    mock.virtual_memory.return_value = vm
    du = MagicMock()
    du.used = int(disk_used * 1024 ** 3)
    du.total = int(disk_total * 1024 ** 3)
    du.percent = disk_pct
    mock.disk_usage.return_value = du
    return mock


def test_get_system_info_basic():
    with patch("psutil.cpu_percent", return_value=25.0), \
         patch("psutil.cpu_count", return_value=8), \
         patch("psutil.virtual_memory") as mock_vm, \
         patch("psutil.disk_usage") as mock_du, \
         patch("core.system_fit.get_gpu_name", return_value=None), \
         patch("core.system_fit.get_gpu_vram_gb", return_value=0.0):
        vm = MagicMock(); vm.used = 4 * 1024**3; vm.total = 16 * 1024**3; vm.percent = 25.0
        mock_vm.return_value = vm
        du = MagicMock(); du.used = 100 * 1024**3; du.total = 500 * 1024**3; du.percent = 20.0
        mock_du.return_value = du
        from modules.system_tools import get_system_info
        result = get_system_info()
    assert "CPU" in result
    assert "RAM" in result
    assert "Disk" in result


def test_get_system_info_includes_gpu():
    with patch("psutil.cpu_percent", return_value=10.0), \
         patch("psutil.cpu_count", return_value=4), \
         patch("psutil.virtual_memory") as mock_vm, \
         patch("psutil.disk_usage") as mock_du, \
         patch("core.system_fit.get_gpu_name", return_value="RTX 4090"), \
         patch("core.system_fit.get_gpu_vram_gb", return_value=24.0):
        vm = MagicMock(); vm.used = 8 * 1024**3; vm.total = 32 * 1024**3; vm.percent = 25.0
        mock_vm.return_value = vm
        du = MagicMock(); du.used = 200 * 1024**3; du.total = 1000 * 1024**3; du.percent = 20.0
        mock_du.return_value = du
        from modules.system_tools import get_system_info
        result = get_system_info()
    assert "RTX 4090" in result
    assert "24.0 GB VRAM" in result


def test_get_system_info_no_gpu():
    with patch("psutil.cpu_percent", return_value=5.0), \
         patch("psutil.cpu_count", return_value=2), \
         patch("psutil.virtual_memory") as mock_vm, \
         patch("psutil.disk_usage") as mock_du, \
         patch("core.system_fit.get_gpu_name", return_value=None), \
         patch("core.system_fit.get_gpu_vram_gb", return_value=0.0):
        vm = MagicMock(); vm.used = 2 * 1024**3; vm.total = 8 * 1024**3; vm.percent = 25.0
        mock_vm.return_value = vm
        du = MagicMock(); du.used = 50 * 1024**3; du.total = 250 * 1024**3; du.percent = 20.0
        mock_du.return_value = du
        from modules.system_tools import get_system_info
        result = get_system_info()
    assert "GPU" not in result


def test_get_vram_status_basic():
    mock_broker = MagicMock()
    mock_broker.status.return_value = {
        "vram_used_gb": 3.5,
        "vram_total_gb": 8.0,
        "studio_mode": False,
        "active_heavy": None,
        "models": {},
    }
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.system_tools import get_vram_status
        result = get_vram_status()
    assert "3.5" in result
    assert "8.0" in result
    assert "studio mode: no" in result.lower()


def test_get_vram_status_studio_mode():
    mock_broker = MagicMock()
    mock_broker.status.return_value = {
        "vram_used_gb": 6.0,
        "vram_total_gb": 8.0,
        "studio_mode": True,
        "active_heavy": "chatterbox",
        "models": {"chatterbox": {"state": "gpu", "vram_gb": 3.0}},
    }
    with patch("voice.vram_broker.get_vram_broker", return_value=mock_broker):
        from modules.system_tools import get_vram_status
        result = get_vram_status()
    assert "studio mode: yes" in result.lower()
    assert "chatterbox" in result


def test_check_system_fit_fits():
    with patch("core.system_fit.check_custom_fit", return_value={"fits": True, "vram_available_gb": 10.0}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        from modules.system_tools import check_system_fit
        result = check_system_fit("mistral-7b", 4.0)
    assert "fits" in result
    assert "mistral-7b" in result


def test_check_system_fit_does_not_fit():
    with patch("core.system_fit.check_custom_fit", return_value={"fits": False, "vram_available_gb": 2.0}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        from modules.system_tools import check_system_fit
        result = check_system_fit("llama-70b", 40.0)
    assert "does not fit" in result
    assert "llama-70b" in result


def test_check_system_fit_includes_llmfit():
    with patch("core.system_fit.check_custom_fit", return_value={"fits": True, "vram_available_gb": 8.0}), \
         patch("core.system_fit.query_llmfit", return_value={
             "models": [{"best_quant": "Q4_K_M", "estimated_tps": 45, "fit_label": "good"}]
         }):
        from modules.system_tools import check_system_fit
        result = check_system_fit("llama-7b", 4.0)
    assert "Q4_K_M" in result
    assert "45" in result
