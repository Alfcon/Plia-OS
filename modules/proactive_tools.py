import asyncio
import core.proactive as _pro_mod
from core.registry import tool


@tool("Get proactive assistant status: whether running, last trigger type, and last message time.")
def proactive_status() -> str:
    pro = _pro_mod.get_proactive()
    running = pro.is_running()
    last_ts = pro.last_message_ts() or "never"
    last_trig = pro.last_trigger_type() or "none"
    status = "running" if running else "stopped"
    return f"Proactive assistant: {status}\nLast trigger: {last_trig}\nLast message: {last_ts}"


@tool("Enable the proactive assistant: starts sending context-aware suggestions via voice and chat.")
def enable_proactive() -> str:
    from core.config import update_config
    pro = _pro_mod.get_proactive()
    update_config(proactive_enabled=True)
    if not pro.is_running():
        try:
            asyncio.get_running_loop().create_task(pro.start())
        except RuntimeError:
            pass
    return "Proactive assistant enabled."


@tool("Disable the proactive assistant: stops all unprompted suggestions.")
def disable_proactive() -> str:
    from core.config import update_config
    pro = _pro_mod.get_proactive()
    update_config(proactive_enabled=False)
    if pro.is_running():
        try:
            asyncio.get_running_loop().create_task(pro.stop())
        except RuntimeError:
            pass
    return "Proactive assistant disabled."
