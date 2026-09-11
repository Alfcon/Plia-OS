from core.registry import tool


@tool(description="Get current system resource usage: CPU, RAM, disk, and GPU info.")
def get_system_info() -> str:
    import platform
    import psutil
    from core.system_fit import get_gpu_name, get_gpu_vram_gb
    cpu = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    ram_used = ram.used / 1024 ** 3
    ram_total = ram.total / 1024 ** 3
    disk_used = disk.used / 1024 ** 3
    disk_total = disk.total / 1024 ** 3
    lines = [
        f"OS: {platform.system()}",
        f"CPU: {cpu:.1f}% ({cpu_count} cores)",
        f"RAM: {ram_used:.1f}/{ram_total:.1f} GB ({ram.percent:.1f}%)",
        f"Disk: {disk_used:.1f}/{disk_total:.1f} GB ({disk.percent:.1f}%)",
    ]
    gpu = get_gpu_name()
    vram = get_gpu_vram_gb()
    if gpu:
        lines.append(f"GPU: {gpu} ({vram:.1f} GB VRAM)")
    return "  ".join(lines)


@tool(description="Show current GPU VRAM usage and which models are loaded on the GPU.")
def get_vram_status() -> str:
    from voice.vram_broker import get_vram_broker
    s = get_vram_broker().status()
    lines = [
        f"VRAM: {s['vram_used_gb']:.1f} / {s['vram_total_gb']:.1f} GB",
        f"Studio mode: {'yes' if s['studio_mode'] else 'no'}",
    ]
    if s.get("active_heavy"):
        lines.append(f"Active heavy model: {s['active_heavy']}")
    models = s.get("models", {})
    if models:
        lines.append("Models:")
        for name, m in models.items():
            lines.append(f"  {name}: {m['state']}" + (f" ({m['vram_gb']:.1f} GB)" if m["state"] == "gpu" else ""))
    return "\n".join(lines)


@tool(description="Check if a model or application will fit on this system's GPU. "
      "Pass the model name and how much GPU VRAM it requires in gigabytes. "
      "Returns whether it fits and how much VRAM is available. "
      "Uses llmfit for extended LLM queries when installed.")
def check_system_fit(model_name: str, vram_required_gb: float) -> str:
    from core.system_fit import check_custom_fit, query_llmfit
    result = check_custom_fit(model_name, vram_required_gb)
    summary = (
        f"{model_name}: {'✓ fits' if result['fits'] else '✗ does not fit'} — "
        f"requires {vram_required_gb:.1f} GB, {result['vram_available_gb']:.1f} GB available."
    )
    llmfit_data = query_llmfit(model_name)
    if llmfit_data:
        models = llmfit_data.get("models", [])
        if models:
            top = models[0]
            summary += (
                f" llmfit: best quant {top.get('best_quant', '?')}, "
                f"est. {top.get('estimated_tps', '?')} tok/s, "
                f"fit={top.get('fit_label', '?')}."
            )
    return summary
