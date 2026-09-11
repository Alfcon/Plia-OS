from __future__ import annotations
import logging
import os
import pathlib
import shlex
import shutil
import subprocess

from core.registry import tool

logger = logging.getLogger(__name__)


def _expand(path: str) -> pathlib.Path:
    if not path:
        return pathlib.Path.home()
    expanded = os.path.expanduser(path)
    p = pathlib.Path(expanded)
    return p.resolve() if p.is_absolute() else (pathlib.Path.home() / p).resolve()


@tool("Read file contents. start_line/end_line are 1-based; negative start_line means last N lines.")
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    p = _expand(path)
    try:
        lines = p.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as exc:
        return f"Error reading {path}: {exc}"

    total = len(lines)
    if start_line < 0:
        lines = lines[start_line:]
    elif start_line > 0 or end_line > 0:
        s = max(0, start_line - 1) if start_line > 0 else 0
        e = end_line if end_line > 0 else total
        lines = lines[s:e]

    return "\n".join(lines) if lines else "(empty file)"


@tool("List directory contents. Defaults to home directory if path is empty.")
def list_directory(path: str = "") -> str:
    p = _expand(path)
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except FileNotFoundError:
        return f"Directory not found: {path or '~'}"
    except NotADirectoryError:
        return f"Not a directory: {path}"
    except Exception as exc:
        return f"Error listing {path}: {exc}"

    if not entries:
        return f"{p} is empty."

    return "\n".join(
        f"[dir]  {e.name}" if e.is_dir() else f"[file] {e.name}"
        for e in entries
    )


@tool("Find files by glob pattern (** supported). Searches home directory if directory is empty.")
def find_files(pattern: str, directory: str = "") -> str:
    base = _expand(directory)
    try:
        matches = sorted(base.glob(pattern))
    except Exception as exc:
        return f"Error searching: {exc}"

    _LIMIT = 100
    total = len(matches)
    truncated = total > _LIMIT
    matches = matches[:_LIMIT]

    if not matches:
        return f"No files found matching '{pattern}' in {base}."

    result = "\n".join(str(m) for m in matches)
    if truncated:
        result += f"\n(showing first {_LIMIT} of {total}+ results)"
    return result


@tool("Search for text within a file. Returns matching lines with 1-based line numbers (case-insensitive).")
def search_in_file(path: str, query: str) -> str:
    p = _expand(path)
    try:
        lines = p.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as exc:
        return f"Error reading {path}: {exc}"

    q = query.lower()
    matches = [f"  {i + 1}: {line}" for i, line in enumerate(lines) if q in line.lower()]

    if not matches:
        return f"No matches for '{query}' in {p}."

    return f"Found {len(matches)} match(es) in {p}:\n" + "\n".join(matches)


@tool("Create or overwrite a file with the given content. Creates parent directories as needed.")
def write_file(path: str, content: str) -> str:
    p = _expand(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    except Exception as exc:
        return f"Error writing {path}: {exc}"
    return f"Written {len(content)} chars to {p}."


@tool("Append text to a file. Creates the file if it does not exist.")
def append_to_file(path: str, content: str) -> str:
    p = _expand(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(content)
    except Exception as exc:
        return f"Error appending to {path}: {exc}"
    return f"Appended {len(content)} chars to {p}."


@tool("Delete a file. Does not delete non-empty directories.")
def delete_file(path: str) -> str:
    p = _expand(path)
    try:
        p.unlink()
    except FileNotFoundError:
        return f"File not found: {path}"
    except IsADirectoryError:
        try:
            p.rmdir()
        except OSError:
            return f"{path} is a non-empty directory."
    except Exception as exc:
        return f"Error deleting {path}: {exc}"
    return f"Deleted {p}."


@tool("Move or rename a file or directory.")
def move_file(source: str, destination: str) -> str:
    src = _expand(source)
    dst = _expand(destination)
    try:
        shutil.move(str(src), str(dst))
    except FileNotFoundError:
        return f"Source not found: {source}"
    except Exception as exc:
        return f"Error moving {source} → {destination}: {exc}"
    return f"Moved {src} → {dst}."


@tool("Copy a file to a new location.")
def copy_file(source: str, destination: str) -> str:
    src = _expand(source)
    dst = _expand(destination)
    try:
        shutil.copy2(str(src), str(dst))
    except FileNotFoundError:
        return f"Source not found: {source}"
    except Exception as exc:
        return f"Error copying {source} → {destination}: {exc}"
    return f"Copied {src} → {dst}."


@tool("Run a file. Python files use 'python', .sh/.bash files use 'bash', others run directly. Captures stdout+stderr, 30s timeout.")
def run_file(path: str, args: str = "") -> str:
    p = _expand(path)
    if not p.exists():
        return f"File not found: {path}"

    suffix = p.suffix.lower()
    if suffix == ".py":
        cmd = ["python", str(p)]
    elif suffix in (".sh", ".bash"):
        cmd = ["bash", str(p)]
    else:
        cmd = [str(p)]

    if args:
        cmd.extend(shlex.split(args))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return f"Timed out after 30 seconds: {p}"
    except Exception as exc:
        return f"Error running {path}: {exc}"

    output = (result.stdout + result.stderr).strip()
    return output if output else f"(no output, exit code {result.returncode})"
