import subprocess
from unittest.mock import patch, MagicMock


def _ok(stdout="", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _err(stderr=""):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


def test_get_now_playing_success():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok("Daft Punk - Get Lucky [spotify]\n")):
        result = get_now_playing()
    assert "Daft Punk" in result
    assert "Get Lucky" in result
    assert "spotify" in result


def test_get_now_playing_empty_metadata():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run", return_value=_ok(" - []\n")):
        result = get_now_playing()
    assert result == "Nothing is playing."


def test_get_now_playing_no_player():
    from modules.media_tools import get_now_playing
    with patch("modules.media_tools.subprocess.run",
               return_value=_err("No players found\n")):
        result = get_now_playing()
    assert result == "No media player is currently running."


def test_media_play_success():
    from modules.media_tools import media_play
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_play()
    assert result == "Done."
    args = mock_run.call_args[0][0]
    assert args[0] == "playerctl"
    assert "play" in args


def test_media_pause_success():
    from modules.media_tools import media_pause
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_pause()
    assert result == "Done."
    assert "pause" in mock_run.call_args[0][0]


def test_media_next_success():
    from modules.media_tools import media_next
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_next()
    assert result == "Done."
    assert "next" in mock_run.call_args[0][0]


def test_media_previous_success():
    from modules.media_tools import media_previous
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_previous()
    assert result == "Done."
    assert "previous" in mock_run.call_args[0][0]


def test_media_stop_success():
    from modules.media_tools import media_stop
    with patch("modules.media_tools.subprocess.run",
               return_value=_ok()) as mock_run:
        result = media_stop()
    assert result == "Done."
    assert "stop" in mock_run.call_args[0][0]


def test_playerctl_not_installed():
    from modules.media_tools import media_play
    with patch("modules.media_tools.subprocess.run", side_effect=FileNotFoundError):
        result = media_play()
    assert "playerctl not installed" in result
    assert "apt install playerctl" in result


def test_playerctl_timeout():
    from modules.media_tools import media_play
    exc = subprocess.TimeoutExpired(cmd=["playerctl", "play"], timeout=5)
    with patch("modules.media_tools.subprocess.run", side_effect=exc):
        result = media_play()
    assert result == "Media command timed out."
