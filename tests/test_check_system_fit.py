import pytest
from unittest.mock import patch


def test_fits_when_vram_sufficient():
    from modules.system_tools import check_system_fit
    with patch("core.system_fit.check_custom_fit", return_value={"fits": True, "vram_available_gb": 8.0}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        result = check_system_fit("llama3", 4.0)
    assert "fits" in result
    assert "llama3" in result


def test_does_not_fit_when_vram_insufficient():
    from modules.system_tools import check_system_fit
    with patch("core.system_fit.check_custom_fit", return_value={"fits": False, "vram_available_gb": 2.0}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        result = check_system_fit("bigmodel", 8.0)
    assert "does not fit" in result
    assert "bigmodel" in result


def test_includes_llmfit_data_when_available():
    from modules.system_tools import check_system_fit
    llmfit_resp = {"models": [{"best_quant": "Q4_K_M", "estimated_tps": 42, "fit_label": "good"}]}
    with patch("core.system_fit.check_custom_fit", return_value={"fits": True, "vram_available_gb": 10.0}), \
         patch("core.system_fit.query_llmfit", return_value=llmfit_resp):
        result = check_system_fit("mymodel", 3.0)
    assert "Q4_K_M" in result
    assert "42" in result


def test_no_llmfit_data_skips_section():
    from modules.system_tools import check_system_fit
    with patch("core.system_fit.check_custom_fit", return_value={"fits": True, "vram_available_gb": 6.0}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        result = check_system_fit("model", 2.0)
    assert "llmfit" not in result


def test_reports_vram_available():
    from modules.system_tools import check_system_fit
    with patch("core.system_fit.check_custom_fit", return_value={"fits": False, "vram_available_gb": 3.5}), \
         patch("core.system_fit.query_llmfit", return_value=None):
        result = check_system_fit("model", 8.0)
    assert "3.5" in result
