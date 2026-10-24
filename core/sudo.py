"""Desktop password prompt for privileged operations.

Plia runs tools from a background web process, so sudo cannot prompt on a
terminal. When a graphical session is available this module installs a small
askpass helper (zenity/kdialog/yad) and exports the sudo environment for the
whole Plia process:

    SUDO_ASKPASS=<helper>
    SUDO_ASKPASS_REQUIRE=force

Every `sudo` launched by a tool then opens a native "Plia needs administrator
access" password dialog. The user types the password into that dialog and sudo
consumes it directly — Plia never sees, buffers or stores it. With a valid sudo
timestamp, later commands run without another prompt.

On a headless host (no DISPLAY, no dialog program) nothing is installed and the
existing behaviour is preserved: sudo fails with its normal password error and
callers show their "grant permission" guidance.
"""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_TITLE = "Plia needs administrator access"

# Password dialogs in preference order: name -> command printing the password.
_DIALOGS: tuple[tuple[str, str], ...] = (
    ("zenity", f'exec timeout 180 zenity --password --title="{_TITLE}" 2>/dev/null'),
    ("kdialog", f'exec timeout 180 kdialog --password "{_TITLE}" 2>/dev/null'),
    ("yad", f'exec timeout 180 yad --password --title="{_TITLE}" 2>/dev/null'),
)

_askpass_path: str | None = None
_lock = threading.Lock()


def _dialog_command() -> str | None:
    for name, command in _DIALOGS:
        if shutil.which(name):
            return command
    return None


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def install_askpass() -> str | None:
    """Create/export the askpass helper for this process (idempotent).

    Returns the helper path, or ``None`` when no graphical password dialog is
    available. Safe to call from any thread.
    """
    global _askpass_path
    with _lock:
        if _askpass_path and Path(_askpass_path).exists():
            return _askpass_path

        # Respect an askpass the user/environment already configured.
        existing = os.environ.get("SUDO_ASKPASS")
        if existing and Path(existing).exists():
            os.environ["SUDO_ASKPASS_REQUIRE"] = "force"
            _askpass_path = existing
            logger.info("Using existing sudo askpass helper: %s", existing)
            return existing

        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return None
        command = _dialog_command()
        if command is None:
            return None

        fd, path = tempfile.mkstemp(prefix="plia-askpass-", suffix=".sh")
        with os.fdopen(fd, "w") as fh:
            fh.write("#!/bin/sh\n" + command + "\n")
        os.chmod(path, 0o700)
        atexit.register(_cleanup, path)

        os.environ["SUDO_ASKPASS"] = path
        os.environ["SUDO_ASKPASS_REQUIRE"] = "force"
        _askpass_path = path
        logger.info("Admin password dialogs enabled (%s)", path)
        return path


def run_sudo(
    args: Sequence[str],
    *,
    input: str | bytes | None = None,
    timeout: float = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a command through sudo, prompting graphically when needed.

    A thin convenience wrapper for new code; existing call sites can simply
    invoke ``sudo`` because the environment is exported process-wide.
    """
    install_askpass()
    return subprocess.run(
        ["sudo", *args],
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def needs_password(stderr: str) -> bool:
    """True when sudo failed because it wanted a password and could not ask."""
    low = (stderr or "").lower()
    return (
        "a password is required" in low
        or "a terminal is required" in low
        or "no tty present" in low
        or "no password was provided" in low
        or "incorrect password" in low
        or "askpass" in low
    )
