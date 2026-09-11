from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 4000

_BLOCKED_REAL = (
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf $home", "mkfs", "dd if=",
    ":(){", "wipefs", "shred ", "chmod -r 000 /", "> /dev/sd",
    "of=/dev/sd", "mv ~ /dev/null", "rm -fr", "--no-preserve-root",
)


def blocked_reason(command: str) -> str | None:
    lower = " ".join(command.lower().split())  # collapse runs of whitespace
    for pattern in _BLOCKED_REAL:
        if pattern in lower:
            return f"Blocked: '{pattern}' is not allowed (destructive)."
    return None


def exec_real(command: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return (output or "(no output)")[:_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return f"Command timed out ({timeout}s)."
    except Exception as exc:
        logger.warning("Real shell error: %s", exc)
        return f"Command error: {exc}"
