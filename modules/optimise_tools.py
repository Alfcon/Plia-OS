"""System optimisation tools — reclaim memory and cut power draw.

Two user-facing actions, both exposed in the dashboard's *Optimise* menu and as
LLM-callable tools:

* :func:`reduce_memory_usage` — unload resident models, clear caches and drop
  the OS page cache.
* :func:`reduce_power_consumption` — unload GPU models and switch the CPU
  governor / energy preference to power-saving.

The privileged steps (CPU governor, energy preference, ``drop_caches``) are
attempted directly first, then through non-interactive ``sudo -n`` when the
``plia-optimise`` sudoers grant exists (see Settings → Permissions). When
neither works the unprivileged steps still run and the report says exactly
which step was skipped and why.

:func:`restore_system_performance` undoes the governor/EPP changes; the
previous values are persisted to ``<memory_dir>/optimise_state.json`` so a
restore still works after a restart.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
from pathlib import Path

from core.registry import tool

logger = logging.getLogger(__name__)

_GOVERNOR_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
_AVAILABLE_GOVERNORS_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_available_governors"
_EPP_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference"
_DROP_CACHES = "/proc/sys/vm/drop_caches"

_POWERSAVE_GOVERNOR = "powersave"
_POWERSAVE_EPP = "power"

_STATE_FILENAME = "optimise_state.json"

_GRANT_HINT = (
    "needs root — grant it in Settings → Permissions → System Optimisation"
)


# ---------------------------------------------------------------------------
# State (previous governor / EPP values, persisted so restore survives restarts)
# ---------------------------------------------------------------------------

def _state_path() -> Path:
    from core.config import get_config
    base = Path(os.path.expanduser(get_config().memory_dir))
    return base / _STATE_FILENAME


_mem_state: dict | None = None
_persist_warned = False


def _read_state() -> dict:
    """Saved state (cached in memory, loaded from disk on first use).

    The in-memory copy is the source of truth for this process, so a restore
    still works even when the state file cannot be written.
    """
    global _mem_state
    if _mem_state is None:
        try:
            data = json.loads(_state_path().read_text())
            _mem_state = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _mem_state = {}
    return _mem_state


def _persist_state() -> None:
    """Best-effort write of the in-memory state so restore survives a restart."""
    global _persist_warned
    state = _read_state()
    path = _state_path()
    if not state:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        if not _persist_warned:
            logger.warning("Could not persist optimise state to %s: %s", path, exc)
            _persist_warned = True


# ---------------------------------------------------------------------------
# Sysfs/proc helpers
# ---------------------------------------------------------------------------

def _privileged_write(path: str, value: str) -> str:
    """Write ``value`` to a root-owned knob.

    Returns ``"ok"``, ``"missing"``, ``"denied"`` or ``"error: ..."``. Tries a
    direct write first (works when Plia itself runs as root) and falls back to
    non-interactive ``sudo -n tee``.
    """
    if not os.path.exists(path):
        return "missing"
    try:
        with open(path, "w") as fh:
            fh.write(value)
        return "ok"
    except PermissionError:
        pass
    except OSError as exc:
        return f"error: {exc}"

    try:
        proc = subprocess.run(
            ["sudo", "-n", "tee", path],
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "error: sudo timed out"
    except OSError as exc:
        return f"error: {exc}"
    return "ok" if proc.returncode == 0 else "denied"


def _set_knob(kind: str, pattern: str, value: str) -> tuple[list[str], list[str]]:
    """Apply ``value`` to every knob matching ``pattern``.

    Returns ``(changed_paths, failed_paths)``. Only knobs that were actually
    changed are recorded for restore, so a permission-denied run leaves no
    phantom "nothing to restore" state behind.
    """
    paths = sorted(glob.glob(pattern))
    if not paths:
        return [], []
    state = _read_state()
    saved = state.get(kind) or {}

    # Capture each knob's current value *before* we overwrite it.
    previous: dict[str, str] = {}
    for path in paths:
        if path in saved:
            previous[path] = saved[path]
        else:
            try:
                previous[path] = Path(path).read_text().strip()
            except OSError:
                previous[path] = ""

    changed: list[str] = []
    failed: list[str] = []
    newly_saved: dict[str, str] = {}
    for path in paths:
        if _privileged_write(path, value) == "ok":
            changed.append(path)
            if previous.get(path) and previous[path] != value:
                newly_saved[path] = previous[path]
        else:
            failed.append(path)

    if newly_saved:
        state[kind] = {**saved, **newly_saved}
        _persist_state()
    return changed, failed


def _restore_knob(kind: str) -> tuple[int, int, set[str]]:
    """Restore values saved for ``kind``. Returns (restored, failed, values)."""
    state = _read_state()
    saved = state.get(kind) or {}
    restored = failed = dropped = 0
    values: set[str] = set()
    remaining: dict[str, str] = {}
    for path, value in saved.items():
        if not value or not os.path.exists(path):
            dropped += 1
            continue
        if _privileged_write(path, value) == "ok":
            restored += 1
            values.add(value)
        else:
            failed += 1
            remaining[path] = value
    if restored or dropped:
        # Keep entries that could not be restored so a later attempt can retry.
        if remaining:
            state[kind] = remaining
        else:
            state.pop(kind, None)
        _persist_state()
    return restored, failed, values


def _available_governors() -> set[str]:
    for path in sorted(glob.glob(_AVAILABLE_GOVERNORS_GLOB)):
        try:
            return set(Path(path).read_text().split())
        except OSError:
            continue
    return set()


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

def _ram_snapshot() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
    except Exception:
        return {}
    gb = 1024 ** 3
    return {
        "used_gb": round(vm.used / gb, 2),
        "total_gb": round(vm.total / gb, 2),
        "available_gb": round(vm.available / gb, 2),
        "percent": round(vm.percent, 1),
    }


def _release_gpu_models() -> list[str]:
    """Unload every model the VRAM broker currently has resident on the GPU."""
    released: list[str] = []
    try:
        from voice.vram_broker import get_vram_broker
        broker = get_vram_broker()
        models = (broker.status().get("models") or {})
        for name, info in models.items():
            if info.get("state") != "gpu":
                continue
            try:
                broker.release(name)
                released.append(name)
            except Exception:
                logger.warning("Could not release model %r", name, exc_info=True)
    except Exception:
        logger.warning("VRAM broker unavailable; no models released", exc_info=True)
    return released


def _clear_app_caches() -> list[str]:
    cleared: list[str] = []
    try:
        from core.supervisor import _RESPONSE_CACHE
        if _RESPONSE_CACHE:
            cleared.append(f"LLM response cache ({len(_RESPONSE_CACHE)} entries)")
            _RESPONSE_CACHE.clear()
    except Exception:
        pass
    try:
        import gc
        gc.collect()
        cleared.append("Python garbage collector")
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            cleared.append("CUDA cache")
    except Exception:
        pass
    return cleared


def _drop_page_cache() -> str:
    if not os.path.exists(_DROP_CACHES):
        return "not available on this system"
    try:
        subprocess.run(["sync"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass
    result = _privileged_write(_DROP_CACHES, "3")
    if result == "ok":
        return "dropped"
    if result == "denied":
        return f"skipped ({_GRANT_HINT})"
    return f"could not drop ({result})"


def _fmt_skipped(failed: list[str], label: str) -> str:
    if not failed:
        return ""
    return f"  {label}: {len(failed)} not changed ({_GRANT_HINT})"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(description="Free up memory: unload resident GPU/Ollama models, clear the LLM "
      "response and CUDA caches, run garbage collection and drop the OS page cache. "
      "Returns a before/after report of what was freed and what was skipped.")
def reduce_memory_usage() -> str:
    before = _ram_snapshot()
    released = _release_gpu_models()
    cleared = _clear_app_caches()
    cache_result = _drop_page_cache()
    after = _ram_snapshot()

    lines = ["Memory optimisation complete."]
    if before and after:
        freed = round(before["used_gb"] - after["used_gb"], 2)
        avail = round(after["available_gb"] - before["available_gb"], 2)
        lines.append(
            f"RAM: {before['used_gb']}/{before['total_gb']} GB ({before['percent']}%) → "
            f"{after['used_gb']}/{after['total_gb']} GB ({after['percent']}%)"
        )
        if freed > 0:
            lines.append(f"Freed: {freed} GB used (available {avail:+.2f} GB)")
        else:
            lines.append(
                f"Freed: none (RAM used {-freed:+.2f} GB, available {avail:+.2f} GB)"
            )
    lines.append(f"Unloaded models: {', '.join(released) if released else 'none'}")
    lines.append(f"Cleared: {', '.join(cleared) if cleared else 'nothing'}")
    lines.append(f"Page cache: {cache_result}")
    return "\n".join(lines)


@tool(description="Reduce power consumption: unload resident GPU/Ollama models and switch "
      "the CPU governor to powersave and the energy preference to 'power'. Needs root for "
      "the CPU settings and falls back gracefully. Undo with restore_system_performance.")
def reduce_power_consumption() -> str:
    released = _release_gpu_models()

    available = _available_governors()
    gov_changed: list[str] = []
    gov_failed: list[str] = []
    gov_note = ""
    if not available:
        gov_note = "no CPU frequency-scaling controls found on this system"
    elif _POWERSAVE_GOVERNOR not in available:
        gov_note = (
            f"this CPU does not offer '{_POWERSAVE_GOVERNOR}' "
            f"(available: {', '.join(sorted(available))})"
        )
    else:
        gov_changed, gov_failed = _set_knob("governor", _GOVERNOR_GLOB, _POWERSAVE_GOVERNOR)

    epp_changed, epp_failed = _set_knob("epp", _EPP_GLOB, _POWERSAVE_EPP)

    lines = ["Power optimisation complete."]
    lines.append(
        f"CPU governor → {_POWERSAVE_GOVERNOR}: {len(gov_changed)} CPU(s) changed"
        + (f" — {gov_note}" if gov_note else "")
    )
    lines.append(f"Energy preference → {_POWERSAVE_EPP}: {len(epp_changed)} CPU(s) changed")
    lines.append(f"Unloaded models: {', '.join(released) if released else 'none'}")
    for extra in (_fmt_skipped(gov_failed, "Governor"), _fmt_skipped(epp_failed, "Energy preference")):
        if extra:
            lines.append(extra)
    if gov_changed or epp_changed:
        lines.append("Run 'restore_system_performance' to return to the previous settings.")
    return "\n".join(lines)


@tool(description="Undo reduce_power_consumption: restore the CPU governor and energy "
      "preference values saved before the power-saving switch.")
def restore_system_performance() -> str:
    gov_restored, gov_failed, gov_values = _restore_knob("governor")
    epp_restored, epp_failed, epp_values = _restore_knob("epp")

    if not gov_restored and not epp_restored:
        if gov_failed or epp_failed:
            return (
                "Could not restore CPU settings — permission denied "
                f"({_GRANT_HINT})."
            )
        return "Nothing to restore — no saved power settings."

    lines = ["Previous performance settings restored."]
    if gov_restored:
        lines.append(
            f"CPU governor → {', '.join(sorted(gov_values)) or 'previous'}: "
            f"{gov_restored} CPU(s) restored"
        )
    if epp_restored:
        lines.append(
            f"Energy preference → {', '.join(sorted(epp_values)) or 'previous'}: "
            f"{epp_restored} CPU(s) restored"
        )
    if gov_failed or epp_failed:
        lines.append(f"Some CPUs could not be restored ({_GRANT_HINT}).")
    return "\n".join(lines)
