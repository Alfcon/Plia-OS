# File Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural-language file system access — read, write, find, search, delete, move, copy, and run files — via a new specialist agent following the existing network/wifi pattern.

**Architecture:** `modules/file_tools.py` provides 10 `@tool`-decorated synchronous functions. `agents/file.py` is a LangGraph node that uses the LLM to parse user intent into an action JSON, then dispatches to the tool functions via `asyncio.to_thread`. `core/supervisor.py` wires it into the graph with keyword routes and an LLM classifier entry.

**Tech Stack:** Python stdlib (`pathlib`, `shutil`, `subprocess`, `glob`), existing `core.registry.tool` decorator, existing `agents.llm.call_llm` / `parse_llm_json`, LangGraph, pytest with `tmp_path` fixture.

## Global Constraints

- Follow the network/wifi agent pattern exactly: `@tool` decorator, synchronous tool functions, async node with `asyncio.to_thread`, LLM JSON parse → fallback on error.
- All tool functions return `str` — never raise to the caller; catch exceptions and return an error string.
- No sandboxing — unrestricted filesystem access (process user permissions apply).
- `delete_file` must not recurse into non-empty directories.
- `run_file`: Python files → `python <path>`, `.sh`/`.bash` → `bash <path>`, other executables → direct invocation. Stdout+stderr captured, 30-second timeout.
- Path handling: `~` expanded via `os.path.expanduser`, relative paths resolved from `~` (via `pathlib.Path.home()`).
- Tests use `tmp_path` pytest fixture — no side effects outside temp dir. `subprocess.run` is mocked in run_file tests.
- Run the full test suite with: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: File tools module

**Files:**
- Create: `modules/file_tools.py`
- Create: `tests/test_file_tools.py`

**Interfaces:**
- Produces:
  - `read_file(path: str, start_line: int = 0, end_line: int = 0) -> str`
  - `list_directory(path: str = "") -> str`
  - `find_files(pattern: str, directory: str = "") -> str`
  - `search_in_file(path: str, query: str) -> str`
  - `write_file(path: str, content: str) -> str`
  - `append_to_file(path: str, content: str) -> str`
  - `delete_file(path: str) -> str`
  - `move_file(source: str, destination: str) -> str`
  - `copy_file(source: str, destination: str) -> str`
  - `run_file(path: str, args: str = "") -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_file_tools.py`:

```python
import subprocess
import pytest
from unittest.mock import patch, MagicMock


# --- read_file ---

def test_read_file_full(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "notes.txt"
    f.write_text("line1\nline2\nline3")
    result = read_file(str(f))
    assert "line1" in result
    assert "line3" in result


def test_read_file_line_range(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "notes.txt"
    f.write_text("a\nb\nc\nd\ne")
    result = read_file(str(f), start_line=2, end_line=4)
    assert "b" in result
    assert "d" in result
    assert "a" not in result
    assert "e" not in result


def test_read_file_negative_start(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "log.txt"
    f.write_text("\n".join(f"line{i}" for i in range(10)))
    result = read_file(str(f), start_line=-3)
    lines = result.strip().splitlines()
    assert len(lines) == 3
    assert "line9" in result


def test_read_file_missing(tmp_path):
    from modules.file_tools import read_file
    result = read_file(str(tmp_path / "nonexistent.txt"))
    assert "not found" in result.lower()


# --- list_directory ---

def test_list_directory_normal(tmp_path):
    from modules.file_tools import list_directory
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "subdir").mkdir()
    result = list_directory(str(tmp_path))
    assert "a.txt" in result
    assert "subdir" in result
    assert "[dir]" in result
    assert "[file]" in result


def test_list_directory_empty(tmp_path):
    from modules.file_tools import list_directory
    empty = tmp_path / "empty"
    empty.mkdir()
    result = list_directory(str(empty))
    assert "empty" in result.lower()


def test_list_directory_missing(tmp_path):
    from modules.file_tools import list_directory
    result = list_directory(str(tmp_path / "no_such_dir"))
    assert "not found" in result.lower()


# --- find_files ---

def test_find_files_match(tmp_path):
    from modules.file_tools import find_files
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = find_files("*.py", str(tmp_path))
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


def test_find_files_no_match(tmp_path):
    from modules.file_tools import find_files
    result = find_files("*.xyz", str(tmp_path))
    assert "no files found" in result.lower()


# --- search_in_file ---

def test_search_in_file_match(tmp_path):
    from modules.file_tools import search_in_file
    f = tmp_path / "data.txt"
    f.write_text("hello world\nfoo bar\nhello again")
    result = search_in_file(str(f), "hello")
    assert "1:" in result
    assert "3:" in result
    assert "2:" not in result


def test_search_in_file_no_match(tmp_path):
    from modules.file_tools import search_in_file
    f = tmp_path / "data.txt"
    f.write_text("nothing relevant here")
    result = search_in_file(str(f), "zzznomatch")
    assert "no matches" in result.lower()


# --- write_file ---

def test_write_file_creates(tmp_path):
    from modules.file_tools import write_file
    f = tmp_path / "new.txt"
    result = write_file(str(f), "hello")
    assert f.read_text() == "hello"
    assert "written" in result.lower()


def test_write_file_overwrites(tmp_path):
    from modules.file_tools import write_file
    f = tmp_path / "existing.txt"
    f.write_text("old content")
    write_file(str(f), "new content")
    assert f.read_text() == "new content"


# --- append_to_file ---

def test_append_to_file_creates(tmp_path):
    from modules.file_tools import append_to_file
    f = tmp_path / "new.txt"
    result = append_to_file(str(f), "first line\n")
    assert f.read_text() == "first line\n"
    assert "appended" in result.lower()


def test_append_to_file_appends(tmp_path):
    from modules.file_tools import append_to_file
    f = tmp_path / "existing.txt"
    f.write_text("line1\n")
    append_to_file(str(f), "line2\n")
    assert f.read_text() == "line1\nline2\n"


# --- delete_file ---

def test_delete_file_success(tmp_path):
    from modules.file_tools import delete_file
    f = tmp_path / "to_delete.txt"
    f.write_text("bye")
    result = delete_file(str(f))
    assert not f.exists()
    assert "deleted" in result.lower()


def test_delete_file_missing(tmp_path):
    from modules.file_tools import delete_file
    result = delete_file(str(tmp_path / "nonexistent.txt"))
    assert "not found" in result.lower()


# --- move_file ---

def test_move_file_success(tmp_path):
    from modules.file_tools import move_file
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("content")
    result = move_file(str(src), str(dst))
    assert not src.exists()
    assert dst.read_text() == "content"
    assert "moved" in result.lower()


# --- copy_file ---

def test_copy_file_success(tmp_path):
    from modules.file_tools import copy_file
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("content")
    result = copy_file(str(src), str(dst))
    assert src.exists()
    assert dst.read_text() == "content"
    assert "copied" in result.lower()


# --- run_file ---

def test_run_file_python(tmp_path):
    from modules.file_tools import run_file
    f = tmp_path / "hello.py"
    f.write_text('print("hello from script")')
    mock_result = MagicMock()
    mock_result.stdout = "hello from script\n"
    mock_result.stderr = ""
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = run_file(str(f))
    assert "hello from script" in result


def test_run_file_timeout(tmp_path):
    from modules.file_tools import run_file
    f = tmp_path / "slow.py"
    f.write_text("import time; time.sleep(100)")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=30)):
        result = run_file(str(f))
    assert "timed out" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_file_tools.py --tb=short -q
```

Expected: errors like `ModuleNotFoundError: No module named 'modules.file_tools'` or `ImportError`.

- [ ] **Step 3: Implement `modules/file_tools.py`**

Create `modules/file_tools.py`:

```python
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

    if not matches:
        return f"No files found matching '{pattern}' in {base}."

    return "\n".join(str(m) for m in matches)


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_file_tools.py --tb=short -q
```

Expected: `22 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/file_tools.py tests/test_file_tools.py
git commit -m "feat(files): add file tools module with 10 registered tool functions"
```

---

### Task 2: File agent

**Files:**
- Create: `agents/file.py`
- Create: `tests/agents/test_file_agent.py`

**Interfaces:**
- Consumes:
  - `agents.llm.call_llm`, `agents.llm.parse_llm_json`
  - All 10 functions from `modules.file_tools` (Task 1)
- Produces:
  - `file_node(state: AgentState) -> dict` — imported by `core/supervisor.py` in Task 3

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_file_agent.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.file import file_node


def _state(user_text: str, prior_results: list | None = None) -> dict:
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": prior_results or [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_invalid_json_returns_fallback():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not json"}
        update = await file_node(_state("read my file"))
    assert update["active_agent"] == "file"
    assert "couldn't parse" in "\n".join(update["tool_results"]).lower()


@pytest.mark.asyncio
async def test_unknown_action_returns_fallback():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": '{"action":"unknown","path":"~/f.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("do unknown file thing"))
    assert update["active_agent"] == "file"
    assert "couldn't parse" in "\n".join(update["tool_results"]).lower()


@pytest.mark.asyncio
async def test_action_read_calls_read_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.read_file", return_value="file contents") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"read","path":"~/notes.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("read ~/notes.txt"))
    mock_fn.assert_called_once_with("~/notes.txt", 0, 0)
    assert update["active_agent"] == "file"
    assert any(r.startswith("[file]") for r in update["tool_results"])
    assert "file contents" in "\n".join(update["tool_results"])


@pytest.mark.asyncio
async def test_action_write_calls_write_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.write_file", return_value="Written 5 chars.") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"write","path":"~/out.txt","destination":null,"content":"hello","query":null,"start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("write hello to ~/out.txt"))
    mock_fn.assert_called_once_with("~/out.txt", "hello")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_action_find_calls_find_files():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.find_files", return_value="/home/user/a.py") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"find","path":"~","destination":null,"content":null,"query":"*.py","start_line":null,"end_line":null,"args":null}'}
        update = await file_node(_state("find all python files"))
    mock_fn.assert_called_once_with("*.py", "~")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_action_run_calls_run_file():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.run_file", return_value="output") as mock_fn:
        mock_llm.return_value = {"content": '{"action":"run","path":"~/script.py","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":"--verbose"}'}
        update = await file_node(_state("run ~/script.py --verbose"))
    mock_fn.assert_called_once_with("~/script.py", "--verbose")
    assert update["active_agent"] == "file"


@pytest.mark.asyncio
async def test_preserves_prior_tool_results():
    with patch("agents.file.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.file.read_file", return_value="contents"):
        mock_llm.return_value = {"content": '{"action":"read","path":"~/f.txt","destination":null,"content":null,"query":null,"start_line":null,"end_line":null,"args":null}'}
        state = _state("read ~/f.txt")
        state["tool_results"] = ["[memory]\nprior"]
        update = await file_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == "[memory]\nprior"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/agents/test_file_agent.py --tb=short -q
```

Expected: `ModuleNotFoundError: No module named 'agents.file'`

- [ ] **Step 3: Implement `agents/file.py`**

Create `agents/file.py`:

```python
from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm, parse_llm_json
from modules.file_tools import (
    read_file, list_directory, find_files, search_in_file,
    write_file, append_to_file, delete_file, move_file, copy_file, run_file,
)

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = (
    "Parse the file system request. "
    "Output JSON with exactly eight keys: "
    '"action" (one of: read, list, find, search, write, append, delete, move, copy, run), '
    '"path" (primary file or directory path string, use ~ for home, or null), '
    '"destination" (destination path for move/copy, otherwise null), '
    '"content" (text content for write/append, otherwise null), '
    '"query" (search string for search action or glob pattern for find, otherwise null), '
    '"start_line" (integer for read line range, negative means last N lines, otherwise null), '
    '"end_line" (integer for read line range end, otherwise null), '
    '"args" (command-line arguments string for run, otherwise null). '
    "Output only valid JSON, no explanation."
)

_FALLBACK_MSG = (
    "[file]\nCouldn't parse that request. "
    "Try: 'read ~/notes.txt', 'list ~/Documents', 'find *.py in ~', "
    "'write hello to ~/test.txt', 'delete ~/temp.txt', 'run ~/script.py'."
)

_ACTIONS = {"read", "list", "find", "search", "write", "append", "delete", "move", "copy", "run"}


async def file_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = parse_llm_json(msg.get("content"))
        action = str(parsed.get("action") or "").strip().lower()
        path = str(parsed.get("path") or "").strip()
        destination = str(parsed.get("destination") or "").strip()
        content = str(parsed.get("content") or "")
        query = str(parsed.get("query") or "").strip()
        start_line = int(parsed["start_line"]) if parsed.get("start_line") is not None else 0
        end_line = int(parsed["end_line"]) if parsed.get("end_line") is not None else 0
        args = str(parsed.get("args") or "").strip()
        if action not in _ACTIONS:
            raise ValueError(f"unknown action: {action!r}")
    except Exception:
        logger.exception("File parse failed for: %r", last_user)
        return {
            "tool_results": state["tool_results"] + [_FALLBACK_MSG],
            "active_agent": "file",
        }

    try:
        if action == "read":
            result = await asyncio.to_thread(read_file, path, start_line, end_line)
        elif action == "list":
            result = await asyncio.to_thread(list_directory, path)
        elif action == "find":
            result = await asyncio.to_thread(find_files, query, path)
        elif action == "search":
            result = await asyncio.to_thread(search_in_file, path, query)
        elif action == "write":
            result = await asyncio.to_thread(write_file, path, content)
        elif action == "append":
            result = await asyncio.to_thread(append_to_file, path, content)
        elif action == "delete":
            result = await asyncio.to_thread(delete_file, path)
        elif action == "move":
            result = await asyncio.to_thread(move_file, path, destination)
        elif action == "copy":
            result = await asyncio.to_thread(copy_file, path, destination)
        else:  # run
            result = await asyncio.to_thread(run_file, path, args)
    except Exception:
        logger.exception("File tool failed for action=%r", action)
        result = "File operation failed. Please try again."

    return {
        "tool_results": state["tool_results"] + [f"[file]\n{result}"],
        "active_agent": "file",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/agents/test_file_agent.py --tb=short -q
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add agents/file.py tests/agents/test_file_agent.py
git commit -m "feat(files): add file agent LangGraph node"
```

---

### Task 3: Wire file agent into supervisor

**Files:**
- Modify: `core/supervisor.py`

**Interfaces:**
- Consumes: `file_node` from `agents.file` (Task 2)
- Produces: "file" intent handled in the LangGraph graph

- [ ] **Step 1: Add import**

In `core/supervisor.py`, after line 19 (`from agents.wifi import wifi_node`), add:

```python
from agents.file import file_node
```

- [ ] **Step 2: Add "file" to `_KNOWN_INTENTS`**

Change line 22 from:
```python
_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder", "network", "wifi"}
```
To:
```python
_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file"}
```

- [ ] **Step 3: Update `_CLASSIFY_SYSTEM`**

Change lines 26–34 from:
```python
_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network. "
    "Use 'reminder' for announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)
```
To:
```python
_CLASSIFY_SYSTEM = (
    "You are a router. Given the conversation, output exactly one word — "
    "the specialist to handle the request: memory, web, code, calendar, home, reminder, network, file. "
    "Use 'reminder' for announcements at a specific future time ('remind me at 3pm', 'notify me in 2 hours'). "
    "Use 'home' only for Home Assistant device control (lights, switches, sensors). "
    "Use 'network' for MAC address operations (show, change, randomize, spoof, restore MAC address). "
    "Use 'wifi' for WiFi status, scanning nearby networks, or listing WiFi interfaces. "
    "Use 'file' for reading, writing, finding, searching, or running files and directories. "
    "Use 'respond' for countdown timers, volume, system info, calculations, or anything answerable with tools directly."
)
```

- [ ] **Step 4: Add keyword routes**

In `_KEYWORD_ROUTES`, after the `"wifi"` entry and before the `"respond"` entry, add:

```python
"file": [
    "read the file", "show me the file", "open the file", "what's in",
    "contents of", "list files", "list directory", "what files",
    "show files in", "find files", "find the file", "search in file",
    "grep ", "create a file", "write to file", "make a file",
    "save to file", "delete the file", "remove the file",
    "move the file", "rename the file", "copy the file",
    "run the file", "run the script", "execute the file",
],
```

- [ ] **Step 5: Add graph node, conditional edge, back-edge**

In `_build_graph()`:

After `g.add_node("wifi", wifi_node)` (line 166), add:
```python
g.add_node("file", file_node)
```

In `g.add_conditional_edges(...)`, after `"wifi": "wifi",` add:
```python
"file": "file",
```

Change the back-edge loop from:
```python
for agent in ("memory", "web", "code", "calendar", "home", "reminder", "network", "wifi"):
```
To:
```python
for agent in ("memory", "web", "code", "calendar", "home", "reminder", "network", "wifi", "file"):
```

- [ ] **Step 6: Run the full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all previous tests pass plus the new 29 tests (22 tool + 7 agent). Total should be 618+.

- [ ] **Step 7: Commit**

```bash
git add core/supervisor.py
git commit -m "feat(files): wire file agent into supervisor graph"
```
