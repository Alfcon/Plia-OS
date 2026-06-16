from unittest.mock import patch


def test_run_python_code_returns_output():
    with patch("agents.code_sandbox.run_python", return_value="42") as mock:
        from modules.example_module import run_python_code
        result = run_python_code("print(6 * 7)")
    mock.assert_called_once_with("print(6 * 7)")
    assert result == "42"


def test_run_python_code_blocked_pattern():
    with patch("agents.code_sandbox.run_python", return_value="Blocked: 'os.system(' is not allowed") as mock:
        from modules.example_module import run_python_code
        result = run_python_code("os.system('ls')")
    assert "Blocked" in result


def test_run_shell_command_returns_output():
    with patch("agents.code_sandbox.run_shell", return_value="hello\n") as mock:
        from modules.example_module import run_shell_command
        result = run_shell_command("echo hello")
    mock.assert_called_once_with("echo hello")
    assert "hello" in result


def test_run_shell_command_blocked_pattern():
    with patch("agents.code_sandbox.run_shell", return_value="Blocked: 'rm -rf' is not allowed") as mock:
        from modules.example_module import run_shell_command
        result = run_shell_command("rm -rf /")
    assert "Blocked" in result


def test_run_python_code_integration():
    from modules.example_module import run_python_code
    result = run_python_code("print(2 + 2)")
    assert "4" in result


def test_run_shell_command_integration():
    from modules.example_module import run_shell_command
    result = run_shell_command("echo 'sandbox works'")
    assert "sandbox" in result
