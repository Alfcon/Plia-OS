import asyncio
import core.observer as _obs_mod
from core.registry import tool


@tool("Get observer status: whether running, last capture time, last profile time, and current profile preview.")
def observer_status() -> str:
    obs = _obs_mod.get_observer()
    running = obs.is_running()
    profile = obs.get_profile()
    last_cap = obs.last_capture_ts() or "never"
    last_prof = obs.last_profile_ts() or "never"
    status = "running" if running else "stopped"
    lines = [f"Observer: {status}", f"Last capture: {last_cap}", f"Last profile: {last_prof}"]
    if profile:
        lines.append(f"Profile: {profile[:300]}")
    else:
        lines.append("Profile: (none yet)")
    return "\n".join(lines)


@tool("Enable the user activity observer: starts screen capture, window focus tracking, and keystroke logging.")
def enable_observer() -> str:
    from core.config import update_config
    obs = _obs_mod.get_observer()
    update_config(observer_enabled=True)
    if not obs.is_running():
        try:
            asyncio.get_running_loop().create_task(obs.start())
        except RuntimeError:
            pass  # no running loop (e.g. tests); API endpoint handles start directly
    return "Observer enabled. Capturing screen, focus, and keystrokes."


@tool("Disable the user activity observer: stops all capture loops.")
def disable_observer() -> str:
    from core.config import update_config
    obs = _obs_mod.get_observer()
    update_config(observer_enabled=False)
    if obs.is_running():
        try:
            asyncio.get_running_loop().create_task(obs.stop())
        except RuntimeError:
            pass
    return "Observer disabled."
