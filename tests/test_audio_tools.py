import subprocess
from unittest.mock import patch, MagicMock
from modules.audio_tools import mute_audio, unmute_audio, set_volume, get_volume


def _run_ok():
    m = MagicMock()
    m.returncode = 0
    return m


def test_mute_audio_success():
    with patch("subprocess.run", return_value=_run_ok()) as mock_run:
        result = mute_audio()
    assert result == "Audio muted."
    mock_run.assert_called_once()
    assert "set-mute" in mock_run.call_args[0][0]
    assert "1" in mock_run.call_args[0][0]


def test_unmute_audio_success():
    with patch("subprocess.run", return_value=_run_ok()) as mock_run:
        result = unmute_audio()
    assert result == "Audio unmuted."
    assert "0" in mock_run.call_args[0][0]


def test_mute_audio_wpctl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = mute_audio()
    assert "wpctl not found" in result


def test_set_volume_valid():
    with patch("subprocess.run", return_value=_run_ok()):
        result = set_volume(75)
    assert result == "Volume set to 75%."


def test_set_volume_out_of_range():
    result = set_volume(101)
    assert "0–100" in result


def test_set_volume_zero():
    with patch("subprocess.run", return_value=_run_ok()):
        result = set_volume(0)
    assert result == "Volume set to 0%."


def test_get_volume_success():
    mock = MagicMock()
    mock.stdout = "Volume: 0.50\n"
    with patch("subprocess.run", return_value=mock):
        result = get_volume()
    assert "50%" in result


def test_get_volume_muted():
    mock = MagicMock()
    mock.stdout = "Volume: 0.30 [MUTED]\n"
    with patch("subprocess.run", return_value=mock):
        result = get_volume()
    assert "muted" in result.lower()


def test_get_volume_wpctl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = get_volume()
    assert "wpctl not found" in result


def test_set_volume_wpctl_error():
    err = subprocess.CalledProcessError(1, "wpctl")
    err.stderr = b"device not found"
    with patch("subprocess.run", side_effect=err):
        result = set_volume(50)
    assert "wpctl error" in result
