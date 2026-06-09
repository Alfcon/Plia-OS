import pytest
from agents.code_sandbox import run_python, run_shell, _check_blocked_python

# --- _check_blocked_python ---

def test_check_blocked_os_system():
    result = _check_blocked_python("os.system('rm -rf /')")
    assert result is not None
    assert "blocked" in result.lower()

def test_check_blocked_shell_true():
    result = _check_blocked_python("subprocess.run(['ls'], shell=True)")
    assert result is not None
    assert "blocked" in result.lower()

def test_check_blocked_socket():
    result = _check_blocked_python("import socket\ns = socket.socket()")
    assert result is not None
    assert "blocked" in result.lower()

def test_check_blocked_urllib():
    result = _check_blocked_python("import urllib.request")
    assert result is not None
    assert "blocked" in result.lower()

def test_check_blocked_allows_safe_code():
    result = _check_blocked_python("x = 1 + 1\nprint(x)")
    assert result is None

# --- run_python ---

def test_run_python_executes_print():
    output = run_python("print('hello from sandbox')")
    assert "hello from sandbox" in output

def test_run_python_captures_stderr():
    output = run_python("import sys; sys.stderr.write('err\\n')")
    assert "err" in output

def test_run_python_returns_error_on_syntax_error():
    output = run_python("def broken(")
    assert len(output) > 0  # some error output

def test_run_python_blocks_os_system():
    output = run_python("import os; os.system('echo pwned')")
    assert "blocked" in output.lower()

def test_run_python_timeout_is_enforced():
    import time
    start = time.monotonic()
    output = run_python("import time; time.sleep(60)", timeout=2)
    elapsed = time.monotonic() - start
    assert elapsed < 10  # must not actually wait 60s
    assert "timed out" in output.lower()

def test_run_python_output_truncated_at_2000():
    output = run_python("print('x' * 5000)")
    assert len(output) <= 2000

# --- run_shell ---

def test_run_shell_executes_echo():
    output = run_shell("echo hello")
    assert "hello" in output

def test_run_shell_captures_stderr():
    output = run_shell("echo oops >&2")
    assert "oops" in output

def test_run_shell_timeout_is_enforced():
    import time
    start = time.monotonic()
    output = run_shell("sleep 60", timeout=2)
    elapsed = time.monotonic() - start
    assert elapsed < 10
    assert "timed out" in output.lower()

def test_run_shell_blocks_rm_rf():
    output = run_shell("rm -rf /tmp/testdir")
    assert "blocked" in output.lower()

def test_run_shell_output_truncated_at_2000():
    output = run_shell("python3 -c \"print('y' * 5000)\"")
    assert len(output) <= 2000
