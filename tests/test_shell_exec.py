from unittest.mock import MagicMock, patch


def test_blocked_reason_catches_destructive():
    from agents.shell_exec import blocked_reason
    assert blocked_reason("rm -rf /") is not None
    assert blocked_reason("sudo RM -RF /") is not None  # case-insensitive
    assert blocked_reason(":(){ :|:& };:") is not None  # fork bomb


def test_blocked_reason_allows_benign_and_network():
    from agents.shell_exec import blocked_reason
    assert blocked_reason("du -sh ~/* | sort -h") is None
    assert blocked_reason("curl https://example.com") is None


def test_blocked_reason_catches_flag_and_spacing_variants():
    from agents.shell_exec import blocked_reason
    assert blocked_reason("rm -fr /") is not None            # swapped flags
    assert blocked_reason("rm  -rf   /") is not None          # collapsed whitespace
    assert blocked_reason("rm -rf --no-preserve-root /") is not None


def test_exec_real_returns_output():
    from agents.shell_exec import exec_real
    r = MagicMock()
    r.stdout = "hello\n"
    r.stderr = ""
    with patch("subprocess.run", return_value=r) as m:
        out = exec_real("echo hello")
    assert "hello" in out
    argv = m.call_args.args[0]
    assert argv[:2] == ["bash", "-c"]


def test_exec_real_timeout():
    import subprocess
    from agents.shell_exec import exec_real
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bash", 60)):
        out = exec_real("sleep 100")
    assert "timed out" in out.lower()


def test_exec_real_error():
    from agents.shell_exec import exec_real
    with patch("subprocess.run", side_effect=OSError("boom")):
        out = exec_real("x")
    assert "error" in out.lower()
