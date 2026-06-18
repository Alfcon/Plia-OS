import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_notification_sent_when_enabled():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = True
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run") as mock_run:
        await _on_reminder_fired({"type": "reminder_fired", "message": "take meds"})
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["notify-send", "Plia Reminder", "take meds"]


@pytest.mark.asyncio
async def test_notification_skipped_when_disabled():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = False
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run") as mock_run:
        await _on_reminder_fired({"type": "reminder_fired", "message": "take meds"})
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_notify_send_missing_does_not_raise():
    from core.notifier import _on_reminder_fired
    mock_cfg = MagicMock()
    mock_cfg.desktop_notifications = True
    with patch("core.notifier.get_config", return_value=mock_cfg), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        await _on_reminder_fired({"type": "reminder_fired", "message": "test"})
    # must not raise
