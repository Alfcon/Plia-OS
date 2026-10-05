import json
from unittest.mock import MagicMock, patch

import pytest

import modules.optimise_tools as opt


@pytest.fixture(autouse=True)
def _reset_optimise_state(monkeypatch):
    """The module caches saved state in memory — isolate it per test."""
    monkeypatch.setattr(opt, "_mem_state", None)
    monkeypatch.setattr(opt, "_persist_warned", False)
    yield


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_tools_register():
    import sys
    from core import registry
    registry.clear_tools()
    # Another test may have unloaded the module; a fresh import re-runs @tool.
    sys.modules.pop("modules.optimise_tools", None)
    import modules.optimise_tools  # noqa: F401
    names = registry.list_tools()
    assert "reduce_memory_usage" in names
    assert "reduce_power_consumption" in names
    assert "restore_system_performance" in names


# ---------------------------------------------------------------------------
# _privileged_write
# ---------------------------------------------------------------------------

def test_privileged_write_direct(tmp_path):
    path = tmp_path / "knob"
    path.write_text("old")
    assert opt._privileged_write(str(path), "new") == "ok"
    assert path.read_text() == "new"


def test_privileged_write_missing():
    assert opt._privileged_write("/definitely/not/a/real/knob", "x") == "missing"


def test_privileged_write_falls_back_to_sudo(monkeypatch, tmp_path):
    path = tmp_path / "knob"
    path.write_text("old")
    real_open = open

    def fake_open(file, mode="r", *args, **kwargs):
        if str(file) == str(path) and "w" in mode:
            raise PermissionError
        return real_open(file, mode, *args, **kwargs)

    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["input"] = kwargs.get("input")
        return MagicMock(returncode=0)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(opt.subprocess, "run", fake_run)

    assert opt._privileged_write(str(path), "powersave") == "ok"
    assert calls["cmd"] == ["sudo", "-n", "tee", str(path)]
    assert calls["input"] == "powersave"


def test_privileged_write_reports_denied(monkeypatch, tmp_path):
    path = tmp_path / "knob"
    path.write_text("old")
    real_open = open

    def fake_open(file, mode="r", *args, **kwargs):
        if str(file) == str(path) and "w" in mode:
            raise PermissionError
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(opt.subprocess, "run", lambda *a, **k: MagicMock(returncode=1))

    assert opt._privileged_write(str(path), "powersave") == "denied"


# ---------------------------------------------------------------------------
# reduce_memory_usage
# ---------------------------------------------------------------------------

def test_reduce_memory_usage_reports_before_and_after(monkeypatch):
    before = {"used_gb": 10.0, "total_gb": 16.0, "available_gb": 5.0, "percent": 62.5}
    after = {"used_gb": 8.0, "total_gb": 16.0, "available_gb": 7.0, "percent": 50.0}
    monkeypatch.setattr(opt, "_ram_snapshot", MagicMock(side_effect=[before, after]))
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: ["ollama"])
    monkeypatch.setattr(opt, "_clear_app_caches", lambda: ["LLM response cache (3 entries)"])
    monkeypatch.setattr(opt, "_drop_page_cache", lambda: "dropped")

    result = opt.reduce_memory_usage()

    assert "Memory optimisation complete." in result
    assert "Freed: 2.0 GB used (available +2.00 GB)" in result
    assert "ollama" in result
    assert "LLM response cache (3 entries)" in result
    assert "Page cache: dropped" in result


def test_reduce_memory_usage_handles_no_psutil(monkeypatch):
    monkeypatch.setattr(opt, "_ram_snapshot", lambda: {})
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])
    monkeypatch.setattr(opt, "_clear_app_caches", lambda: [])
    monkeypatch.setattr(opt, "_drop_page_cache", lambda: "skipped (needs root)")

    result = opt.reduce_memory_usage()

    assert "Unloaded models: none" in result
    assert "Cleared: nothing" in result


def test_reduce_memory_usage_no_net_free(monkeypatch):
    before = {"used_gb": 8.0, "total_gb": 16.0, "available_gb": 7.0, "percent": 50.0}
    after = {"used_gb": 8.2, "total_gb": 16.0, "available_gb": 6.8, "percent": 51.2}
    monkeypatch.setattr(opt, "_ram_snapshot", MagicMock(side_effect=[before, after]))
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])
    monkeypatch.setattr(opt, "_clear_app_caches", lambda: [])
    monkeypatch.setattr(opt, "_drop_page_cache", lambda: "dropped")

    result = opt.reduce_memory_usage()

    assert "Freed: none" in result


# ---------------------------------------------------------------------------
# _release_gpu_models
# ---------------------------------------------------------------------------

def test_release_gpu_models_only_touches_resident():
    broker = MagicMock()
    broker.status.return_value = {
        "models": {
            "ollama": {"state": "gpu"},
            "whisper": {"state": "unloaded"},
        }
    }
    with patch("voice.vram_broker.get_vram_broker", return_value=broker):
        released = opt._release_gpu_models()

    assert released == ["ollama"]
    broker.release.assert_called_once_with("ollama")


# ---------------------------------------------------------------------------
# reduce_power_consumption / restore_system_performance
# ---------------------------------------------------------------------------

def _make_cpufreq(tmp_path, governor="schedutil", epp="balance_performance",
                  available="schedutil powersave performance"):
    freq = tmp_path / "cpu0" / "cpufreq"
    freq.mkdir(parents=True)
    gov = freq / "scaling_governor"
    gov.write_text(governor)
    epp_path = freq / "energy_performance_preference"
    epp_path.write_text(epp)
    avail = freq / "scaling_available_governors"
    avail.write_text(available)
    return gov, epp_path, avail


def _patch_glob(monkeypatch, gov, epp, avail, all_cpus=None):
    def fake_glob(pattern):
        if pattern == opt._AVAILABLE_GOVERNORS_GLOB:
            return [str(avail)]
        if pattern == opt._EPP_GLOB:
            return [str(epp)]
        if pattern == opt._GOVERNOR_GLOB:
            return [str(p) for p in (all_cpus or [gov])]
        return []

    monkeypatch.setattr(opt.glob, "glob", fake_glob)


def test_reduce_power_sets_powersave_and_restore_undoes_it(monkeypatch, tmp_path):
    gov, epp, avail = _make_cpufreq(tmp_path)
    _patch_glob(monkeypatch, gov, epp, avail)
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: ["ollama"])

    result = opt.reduce_power_consumption()

    assert gov.read_text().strip() == "powersave"
    assert epp.read_text().strip() == "power"
    assert "ollama" in result
    assert "1 CPU(s) changed" in result

    restored = opt.restore_system_performance()
    assert gov.read_text().strip() == "schedutil"
    assert epp.read_text().strip() == "balance_performance"
    assert "restored" in restored.lower()


def test_reduce_power_reports_unsupported_governor(monkeypatch, tmp_path):
    gov, epp, avail = _make_cpufreq(tmp_path, available="schedutil performance")
    _patch_glob(monkeypatch, gov, epp, avail)
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])

    result = opt.reduce_power_consumption()

    assert "does not offer" in result
    assert gov.read_text().strip() == "schedutil"


def test_reduce_power_without_cpufreq(monkeypatch):
    monkeypatch.setattr(opt.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])

    result = opt.reduce_power_consumption()

    assert "no CPU frequency-scaling controls" in result


def test_restore_without_saved_state(monkeypatch):
    monkeypatch.setattr(opt.glob, "glob", lambda pattern: [])
    result = opt.restore_system_performance()
    assert "Nothing to restore" in result


def test_state_persists_previous_governor(monkeypatch, tmp_path):
    state_file = tmp_path / "optimise_state.json"
    monkeypatch.setattr(opt, "_state_path", lambda: state_file)

    gov, epp, avail = _make_cpufreq(tmp_path)
    _patch_glob(monkeypatch, gov, epp, avail)
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])

    opt.reduce_power_consumption()

    saved = json.loads(state_file.read_text())
    assert saved["governor"][str(gov)] == "schedutil"
    assert saved["epp"][str(epp)] == "balance_performance"


def test_restore_works_when_state_file_unwritable(monkeypatch, tmp_path):
    # A directory at the state path makes persistence fail; the in-memory copy
    # must still let restore undo the governor change within this process.
    blocked = tmp_path / "state.json"
    blocked.mkdir()
    monkeypatch.setattr(opt, "_state_path", lambda: blocked)

    gov, epp, avail = _make_cpufreq(tmp_path)
    _patch_glob(monkeypatch, gov, epp, avail)
    monkeypatch.setattr(opt, "_release_gpu_models", lambda: [])

    opt.reduce_power_consumption()
    assert gov.read_text().strip() == "powersave"

    opt.restore_system_performance()
    assert gov.read_text().strip() == "schedutil"
    assert epp.read_text().strip() == "balance_performance"


def test_restore_keeps_entries_that_could_not_be_restored(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(opt, "_state_path", lambda: state_file)
    gov1 = tmp_path / "cpu0" / "scaling_governor"
    gov2 = tmp_path / "cpu1" / "scaling_governor"
    gov1.parent.mkdir(parents=True)
    gov2.parent.mkdir(parents=True)
    gov1.write_text("powersave")
    gov2.write_text("powersave")
    state_file.write_text(json.dumps({
        "governor": {str(gov1): "schedutil", str(gov2): "performance"},
    }))

    monkeypatch.setattr(
        opt, "_privileged_write",
        lambda path, value: "ok" if path == str(gov1) else "denied",
    )

    restored, failed, values = opt._restore_knob("governor")

    assert restored == 1
    assert failed == 1
    assert values == {"schedutil"}
    # The CPU that could not be restored stays saved for a later retry.
    assert json.loads(state_file.read_text())["governor"] == {str(gov2): "performance"}
