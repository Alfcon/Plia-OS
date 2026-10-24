from __future__ import annotations
import logging
import os
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 2000
_SAFE_PATH = "/usr/bin:/bin"

_BLOCKED_PYTHON = (
    "os.system(",
    "shell=True",
    "import socket",
    "from socket",
    "import urllib",
    "from urllib",
)

_BLOCKED_SHELL = (
    "rm -rf",
    "dd if=",
    "mkfs",
    "> /dev/",
    "curl ",
    "wget ",
    " nc ",
    "ncat ",
)


def _check_blocked_python(code: str) -> str | None:
    for pattern in _BLOCKED_PYTHON:
        if pattern in code:
            return f"Blocked: '{pattern}' is not allowed"
    return None


def run_python(code: str, timeout: int = 30) -> str:
    blocked = _check_blocked_python(code)
    if blocked:
        return blocked

    with tempfile.TemporaryDirectory() as tmpdir:
        code_file = os.path.join(tmpdir, "code.py")
        with open(code_file, "w") as f:
            f.write(code)
        try:
            result = subprocess.run(
                [sys.executable, code_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env={"PATH": _SAFE_PATH, "HOME": "/tmp", "PYTHONPATH": ""},
            )
            output = result.stdout + result.stderr
            return (output or "(no output)")[:_MAX_OUTPUT]
        except subprocess.TimeoutExpired:
            return f"Execution timed out ({timeout}s limit)"
        except Exception as exc:
            logger.warning("Python sandbox error: %s", exc)
            return f"Execution error: {exc}"


def run_shell(command: str, timeout: int = 30) -> str:
    lower = command.lower()
    for pattern in _BLOCKED_SHELL:
        if pattern in lower:
            return f"Blocked: '{pattern}' is not allowed in shell commands"

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": _SAFE_PATH, "HOME": "/tmp"},
        )
        output = result.stdout + result.stderr
        return (output or "(no output)")[:_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return f"Execution timed out ({timeout}s limit)"
    except Exception as exc:
        logger.warning("Shell sandbox error: %s", exc)
        return f"Execution error: {exc}"
