"""
Destructive command blocklist for /api/shell.
Raises ShellBlockedError on pattern match.
"""
from __future__ import annotations
import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r':\s*\(\s*\)\s*\{.*:\s*\|', re.DOTALL), "fork bomb"),
    (re.compile(r'\bdd\b.{0,300}\bof\s*=\s*/dev/[a-z]', re.DOTALL), "dd to raw device"),
    (re.compile(r'\bmkfs\b'), "filesystem format"),
    (re.compile(r'(?:>>?)\s*/dev/sd'), "write redirect to block device"),
    # rm with recursive flag where target is root dir (/ followed by whitespace, * or end — not /subdir)
    (re.compile(r'\brm\b[^|&;\n]*-[a-zA-Z]*[rR][a-zA-Z]*[^|&;\n]*/(?:\s|$|\*)', re.MULTILINE), "rm -r on /"),
    (re.compile(r'\bshred\b.{0,200}/dev/'), "shred on device"),
]


class ShellBlockedError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Command blocked: {reason}")
        self.reason = reason


def check_command(cmd: str) -> None:
    """Raise ShellBlockedError if cmd matches a destructive pattern."""
    for pattern, reason in _RULES:
        if pattern.search(cmd):
            raise ShellBlockedError(reason)
