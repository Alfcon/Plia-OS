from core.registry import tool


@tool(description="Execute Python code in a sandbox and return output. Useful for calculations, data processing, or quick scripts.")
def run_python_code(code: str) -> str:
    from agents.code_sandbox import run_python
    return run_python(code)


@tool(description="Run a shell command in a restricted sandbox and return output. Useful for file listings, text processing, system info.")
def run_shell_command(command: str) -> str:
    from agents.code_sandbox import run_shell
    return run_shell(command)
