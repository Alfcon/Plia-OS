# Code Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the code agent stub with a sandboxed execution node that safely runs Python snippets and shell commands with a 30-second timeout and blocked dangerous patterns.

**Architecture:** `agents/code_sandbox.py` owns execution — it checks for blocked patterns, writes code to a temp directory, and runs it in a subprocess (Python via the venv interpreter, shell via `bash -c` with restricted PATH). `agents/code.py` is the LangGraph node — it uses `call_llm` to extract code and detect language from the user message, dispatches to the sandbox, and returns output in `tool_results`. No new dependencies; only stdlib (`subprocess`, `tempfile`, `sys`, `os`, `json`).

**Tech Stack:** Python stdlib subprocess, tempfile, sys, os; LangGraph (existing); call_llm (existing)

---

## File Structure

```
agents/
  code_sandbox.py   NEW  — run_python(), run_shell(), _check_blocked_python()
  code.py           MOD  — replace stub with real LangGraph node

tests/agents/
  test_code_sandbox.py  NEW  — unit tests for sandbox execution
  test_code_node.py     NEW  — unit tests for code_node
```

---

### Task 1: agents/code_sandbox.py — execution engine

**Files:**
- Create: `agents/code_sandbox.py`
- Create: `tests/agents/test_code_sandbox.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_code_sandbox.py`:

```python
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
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_code_sandbox.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'agents.code_sandbox'`

- [ ] **Step 3: Create agents/code_sandbox.py**

```python
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
                env={**os.environ, "PYTHONPATH": ""},
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
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_code_sandbox.py -v
```

Expected: 15 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥129)

- [ ] **Step 6: Commit**

```bash
git add agents/code_sandbox.py tests/agents/test_code_sandbox.py
git commit -m "feat: add code sandbox with Python and shell execution (blocked patterns, timeout)"
```

---

### Task 2: agents/code.py — real LangGraph node

**Files:**
- Modify: `agents/code.py`
- Create: `tests/agents/test_code_node.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/agents/test_code_node.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.code import code_node


def _state(user_text):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": "ddg",
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_code_node_runs_python_and_returns_output():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="42\n") as mock_py:
        mock_llm.return_value = {"content": '{"language":"python","code":"print(6*7)"}'}
        update = await code_node(_state("run this: print(6*7)"))
    mock_py.assert_called_once_with("print(6*7)")
    assert update["active_agent"] == "code"
    assert any("42" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_code_node_runs_shell_and_returns_output():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_shell", return_value="hello\n") as mock_sh:
        mock_llm.return_value = {"content": '{"language":"shell","code":"echo hello"}'}
        update = await code_node(_state("run shell: echo hello"))
    mock_sh.assert_called_once_with("echo hello")
    assert update["active_agent"] == "code"
    assert any("hello" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_code_node_defaults_to_python_on_unknown_language():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="ok\n") as mock_py:
        mock_llm.return_value = {"content": '{"language":"ruby","code":"puts 42"}'}
        update = await code_node(_state("run puts 42"))
    mock_py.assert_called_once_with("puts 42")
    assert update["active_agent"] == "code"


@pytest.mark.asyncio
async def test_code_node_llm_parse_error_falls_back_to_python():
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="result\n") as mock_py:
        mock_llm.return_value = {"content": "not json at all"}
        update = await code_node(_state("print('hello')"))
    mock_py.assert_called_once()
    assert update["active_agent"] == "code"


@pytest.mark.asyncio
async def test_code_node_accumulates_tool_results():
    existing = ["[memory]\nprevious context"]
    state = _state("run print(1)")
    state["tool_results"] = existing
    with patch("agents.code.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.code.run_python", return_value="1\n"):
        mock_llm.return_value = {"content": '{"language":"python","code":"print(1)"}'}
        update = await code_node(state)
    assert len(update["tool_results"]) == 2
    assert update["tool_results"][0] == existing[0]
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/agents/test_code_node.py -v 2>&1 | head -15
```

Expected: FAIL — stub always returns "[code] not yet implemented" and never calls run_python/run_shell.

- [ ] **Step 3: Replace agents/code.py**

```python
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.code_sandbox import run_python, run_shell

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "Extract the code from the user's message. "
    'Output JSON with two keys: "language" ("python" or "shell") and "code" (the code string). '
    "Output only valid JSON, no explanation."
)


async def code_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )

    try:
        msg = await call_llm([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        parsed = json.loads(msg.get("content", "{}"))
        language = parsed.get("language", "python")
        code = parsed.get("code", last_user)
    except Exception:
        language, code = "python", last_user

    if language == "shell":
        output = run_shell(code)
    else:
        output = run_python(code)

    logger.info("Code execution (%s): %d chars output", language, len(output))
    return {
        "tool_results": state["tool_results"] + [f"[code/{language}]\n{output}"],
        "active_agent": "code",
    }
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_code_node.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥144)

- [ ] **Step 6: Commit**

```bash
git add agents/code.py tests/agents/test_code_node.py
git commit -m "feat: implement code agent node with Python/shell dispatch"
```
