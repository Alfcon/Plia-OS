from core.registry import tool


@tool(description="Stop the voice pipeline (wake word, STT, TTS). Use when asked to 'go to sleep' or 'stop listening'.")
async def stop_voice_pipeline() -> str:
    from core import pipeline_registry, watchdog
    task = pipeline_registry.get_task()
    if task and not task.done():
        task.cancel()
        # In-memory only — this is a transient pipeline action, not a
        # watchdog-panel stop, so don't persist "stopped" (that would block
        # the voice_pipeline watchdog task from spawning at next boot).
        watchdog.mark_stopped_transient("voice_pipeline")
        return "Voice pipeline stopping."
    return "Pipeline is not running."


@tool(description="Start the voice pipeline. Use when asked to 'wake up' or 'start listening'.")
async def start_voice_pipeline() -> str:
    import asyncio
    from core import pipeline_registry, watchdog
    from core import pipeline_runner
    task = pipeline_registry.get_task()
    if task and not task.done():
        return "Pipeline is already running."
    new_task = asyncio.get_running_loop().create_task(pipeline_runner.start_pipeline(), name="pipeline_start")
    pipeline_registry.set_task(new_task)
    watchdog.set_task("voice_pipeline", new_task)
    watchdog.clear_state("voice_pipeline")
    return "Voice pipeline starting."


@tool(description="Speak a message aloud via the voice pipeline TTS. Use to announce something without waiting for user input.")
async def announce(message: str) -> str:
    from core import events
    await events.emit("speak", {"message": message})
    return f"Announcing: {message}"
