import core.tor_manager as _tm
from core.registry import tool


@tool("Enable system-wide Tor routing — routes all network traffic through the Tor anonymity network.")
def enable_tor() -> str:
    return _tm.enable()


@tool("Disable Tor routing and restore direct clearnet network access.")
def disable_tor() -> str:
    return _tm.disable()


@tool("Get current Tor status: whether enabled, exit node IP, and kill switch state.")
def tor_status() -> str:
    status = _tm.get_status()
    if status["kill_switch_active"]:
        return "Tor kill switch active — all traffic blocked. Run 'enable tor' to reconnect."
    if status["enabled"]:
        ip = status.get("exit_ip") or "unknown"
        return f"Tor enabled. Exit node: {ip}"
    return "Tor disabled. Traffic routes directly (clearnet)."
