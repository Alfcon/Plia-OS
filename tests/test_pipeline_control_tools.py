import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch


def test_pipeline_tools_are_async():
    # Sync tools are dispatched to a thread pool by call_tool_async, where
    # there is no event loop — these tools touch the loop so they must be async.
    from modules import pipeline_tools
    assert inspect.iscoroutinefunction(pipeline_tools.stop_voice_pipeline)
    assert inspect.iscoroutinefunction(pipeline_tools.start_voice_pipeline)
    assert inspect.iscoroutinefunction(pipeline_tools.announce)


def test_stop_voice_pipeline_cancels_task():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    with patch("core.pipeline_registry.get_task", return_value=mock_task):
        from modules.pipeline_tools import stop_voice_pipeline
        result = asyncio.run(stop_voice_pipeline())
    mock_task.cancel.assert_called_once()
    assert "stopping" in result.lower()


def test_stop_voice_pipeline_not_running():
    with patch("core.pipeline_registry.get_task", return_value=None):
        from modules.pipeline_tools import stop_voice_pipeline
        result = asyncio.run(stop_voice_pipeline())
    assert "not running" in result.lower()


def test_stop_voice_pipeline_already_done():
    mock_task = MagicMock()
    mock_task.done.return_value = True
    with patch("core.pipeline_registry.get_task", return_value=mock_task):
        from modules.pipeline_tools import stop_voice_pipeline
        result = asyncio.run(stop_voice_pipeline())
    assert "not running" in result.lower()


def test_start_voice_pipeline_when_stopped():
    started = asyncio.Event()

    async def fake_start():
        started.set()

    async def run():
        from modules.pipeline_tools import start_voice_pipeline
        result = await start_voice_pipeline()
        await asyncio.wait_for(started.wait(), timeout=1)
        return result

    with patch("core.pipeline_registry.get_task", return_value=None), \
         patch("core.pipeline_registry.set_task") as mock_set, \
         patch("core.pipeline_runner.start_pipeline", side_effect=fake_start):
        result = asyncio.run(run())
    mock_set.assert_called_once()
    assert "starting" in result.lower()


def test_start_voice_pipeline_already_running():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    with patch("core.pipeline_registry.get_task", return_value=mock_task):
        from modules.pipeline_tools import start_voice_pipeline
        result = asyncio.run(start_voice_pipeline())
    assert "already running" in result.lower()


def test_announce_emits_speak():
    with patch("core.events.emit", new=AsyncMock()) as mock_emit:
        from modules.pipeline_tools import announce
        result = asyncio.run(announce("Hello"))
    mock_emit.assert_awaited_once_with("speak", {"message": "Hello"})
    assert "Hello" in result
