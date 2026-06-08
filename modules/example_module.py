from core.registry import tool


@tool(description="Get the current time in HH:MM format")
def get_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


@tool(description="Set a reminder message to fire in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    return f"Reminder set: '{message}' in {minutes} minute(s)."


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
    # Try llmfit for additional LLM-specific info (e.g. quantisation advice)
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
