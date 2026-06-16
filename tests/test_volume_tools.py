from unittest.mock import patch, MagicMock
import subprocess


def test_set_volume_calls_wpctl():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from modules.example_module import set_volume
        result = set_volume(75)
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "wpctl"
    assert "0.75" in args
    assert "75%" in result


def test_set_volume_rejects_out_of_range():
    from modules.example_module import set_volume
    assert "0" in set_volume(-1) or "100" in set_volume(-1)
    assert "0" in set_volume(101) or "100" in set_volume(101)


def test_set_volume_zero():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from modules.example_module import set_volume
        result = set_volume(0)
    args = mock_run.call_args[0][0]
    assert "0.00" in args
    assert "0%" in result


def test_set_volume_wpctl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        from modules.example_module import set_volume
        result = set_volume(50)
    assert "not found" in result.lower()


def test_get_volume_parses_output():
    mock_result = MagicMock()
    mock_result.stdout = "Volume: 0.75\n"
    with patch("subprocess.run", return_value=mock_result):
        from modules.example_module import get_volume
        result = get_volume()
    assert "75%" in result


def test_get_volume_muted():
    mock_result = MagicMock()
    mock_result.stdout = "Volume: 0.50 [MUTED]\n"
    with patch("subprocess.run", return_value=mock_result):
        from modules.example_module import get_volume
        result = get_volume()
    assert "50%" in result
    assert "muted" in result.lower()


def test_get_volume_wpctl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        from modules.example_module import get_volume
        result = get_volume()
    assert "not found" in result.lower()
