from core.registry import tool


@tool(description="Stop the voice pipeline (wake word, STT, TTS). Use when asked to 'go to sleep' or 'stop listening'.")
def stop_voice_pipeline() -> str:
    import asyncio
    from core import pipeline_registry
    task = pipeline_registry.get_task()
    if task and not task.done():
        asyncio.get_event_loop().call_soon_threadsafe(task.cancel)
        return "Voice pipeline stopping."
    return "Pipeline is not running."


@tool(description="Start the voice pipeline. Use when asked to 'wake up' or 'start listening'.")
def start_voice_pipeline() -> str:
    import asyncio
    from core import pipeline_registry
    from core.pipeline_runner import start_pipeline as _start
    task = pipeline_registry.get_task()
    if task and not task.done():
        return "Pipeline is already running."
    new_task = asyncio.get_event_loop().create_task(_start())
    pipeline_registry.set_task(new_task)
    return "Voice pipeline starting."


@tool(description="Speak a message aloud via the voice pipeline TTS. Use to announce something without waiting for user input.")
def announce(message: str) -> str:
    import asyncio
    from core import events
    asyncio.get_event_loop().create_task(events.emit("speak", {"message": message}))
    return f"Announcing: {message}"
