import asyncio
from unittest.mock import MagicMock, patch


def test_stop_voice_pipeline_cancels_task():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    with patch("core.pipeline_registry.get_task", return_value=mock_task), \
         patch("asyncio.get_event_loop") as mock_loop:
        from modules.example_module import stop_voice_pipeline
        result = stop_voice_pipeline()
    mock_loop.return_value.call_soon_threadsafe.assert_called_once_with(mock_task.cancel)
    assert "stopping" in result.lower()


def test_stop_voice_pipeline_not_running():
    with patch("core.pipeline_registry.get_task", return_value=None):
        from modules.example_module import stop_voice_pipeline
        result = stop_voice_pipeline()
    assert "not running" in result.lower()


def test_stop_voice_pipeline_already_done():
    mock_task = MagicMock()
    mock_task.done.return_value = True
    with patch("core.pipeline_registry.get_task", return_value=mock_task):
        from modules.example_module import stop_voice_pipeline
        result = stop_voice_pipeline()
    assert "not running" in result.lower()


def test_start_voice_pipeline_when_stopped():
    mock_task = MagicMock()
    with patch("core.pipeline_registry.get_task", return_value=None), \
         patch("core.pipeline_registry.set_task") as mock_set, \
         patch("asyncio.get_event_loop") as mock_loop, \
         patch("core.pipeline_runner.start_pipeline"):
        mock_loop.return_value.create_task.return_value = mock_task
        from modules.example_module import start_voice_pipeline
        result = start_voice_pipeline()
    mock_set.assert_called_once_with(mock_task)
    assert "starting" in result.lower()


def test_start_voice_pipeline_already_running():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    with patch("core.pipeline_registry.get_task", return_value=mock_task):
        from modules.example_module import start_voice_pipeline
        result = start_voice_pipeline()
    assert "already running" in result.lower()
