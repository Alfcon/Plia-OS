# File Agent Design

## Goal

Add natural-language file system access to Plia-OS: read, write, find, search, delete, move, copy, and run files anywhere on the filesystem the process user can reach.

## Architecture

Thin agent + rich tool registry pattern (same as network/wifi agents). Three new files, one edited:

- `modules/file_tools.py` — 10 `@tool`-decorated synchronous functions
- `agents/file.py` — LangGraph node; LLM parses user intent to action JSON, dispatches to tools via `asyncio.to_thread`
- `core/supervisor.py` — add "file" intent, keyword routes, graph node/edge
- `tests/test_file_tools.py` — unit tests using `tmp_path`
- `tests/agents/test_file_agent.py` — agent dispatch tests mocking LLM + tools

## Tool Functions (`modules/file_tools.py`)

All registered via `@tool`. All synchronous. All return a plain string (result or error message).

| Function | Signature | Behaviour |
|---|---|---|
| `read_file` | `(path: str, start_line: int = 0, end_line: int = 0) -> str` | Reads file. `start_line`/`end_line` are 1-based; negative `start_line` means "last N lines". Returns content or error. |
| `list_directory` | `(path: str = "") -> str` | Lists directory entries. Empty path → `~`. Returns newline-separated names with type indicator (`[dir]`/`[file]`). |
| `find_files` | `(pattern: str, directory: str = "") -> str` | Glob search (`**` supported). Empty directory → `~`. Returns matching paths, one per line. |
| `search_in_file` | `(path: str, query: str) -> str` | Searches file for query string (case-insensitive). Returns matching lines with line numbers. |
| `write_file` | `(path: str, content: str) -> str` | Creates or overwrites file. Creates parent directories as needed. |
| `append_to_file` | `(path: str, content: str) -> str` | Appends content to file. Creates file if missing. |
| `delete_file` | `(path: str) -> str` | Deletes file. Returns error if not found. Does not delete non-empty directories. |
| `move_file` | `(source: str, destination: str) -> str` | Moves or renames file/directory. |
| `copy_file` | `(source: str, destination: str) -> str` | Copies file to destination. |
| `run_file` | `(path: str, args: str = "") -> str` | Runs file. Python files → `python <path> <args>`. Shell scripts → `bash <path> <args>`. Executables → direct. Captures stdout+stderr. 30s timeout. |

Path handling: `~` expanded via `os.path.expanduser`. Relative paths resolved from `~`.

`run_file` is distinct from the code agent: code agent runs inline pasted code; file agent runs existing files on disk.

## Agent (`agents/file.py`)

LLM is given a fixed system prompt that outputs exactly 8 keys:

```json
{
  "action": "read|list|find|search|write|append|delete|move|copy|run",
  "path": "<primary path string>",
  "destination": "<string or null>",
  "content": "<string or null>",
  "query": "<string or null>",
  "start_line": "<int or null>",
  "end_line": "<int or null>",
  "args": "<string or null>"
}
```

On parse failure or unknown action: return `[file]\nCouldn't parse that request.` fallback (same pattern as network/wifi agents).

On tool exception: return `[file]\nFile operation failed. Please try again.`

Returns `{"tool_results": [..., "[file]\n<result>"], "active_agent": "file"}`.

## Supervisor (`core/supervisor.py`)

Add to `_KNOWN_INTENTS`:
```python
"file"
```

Add to `_CLASSIFY_SYSTEM`:
```
Use 'file' for reading, writing, finding, searching, or running files and directories.
```

Add keyword routes:
```python
"file": [
    "read the file", "show me the file", "open the file", "what's in",
    "contents of", "list files", "list directory", "what files",
    "show files in", "find files", "find the file", "search in file",
    "grep ", "create a file", "write to file", "make a file",
    "save to file", "delete the file", "remove the file",
    "move the file", "rename the file", "copy the file",
    "run the file", "run the script", "execute the file",
]
```

Add graph node `g.add_node("file", file_node)`, conditional edge `"file": "file"`, and include `"file"` in the back-edge loop to supervisor.

## Tests

### `tests/test_file_tools.py`

Uses `tmp_path` pytest fixture — no real filesystem side effects outside temp dir.

| Test | Covers |
|---|---|
| `test_read_file_full` | reads entire file |
| `test_read_file_line_range` | start_line/end_line slice |
| `test_read_file_negative_start` | last N lines |
| `test_read_file_missing` | error string returned |
| `test_list_directory_normal` | lists files and dirs |
| `test_list_directory_empty` | empty dir returns message |
| `test_list_directory_missing` | error string |
| `test_find_files_match` | glob finds files |
| `test_find_files_no_match` | returns "no files found" |
| `test_search_in_file_match` | returns line numbers |
| `test_search_in_file_no_match` | returns "no matches" |
| `test_write_file_creates` | creates new file |
| `test_write_file_overwrites` | overwrites existing |
| `test_append_to_file_creates` | creates if missing |
| `test_append_to_file_appends` | appends to existing |
| `test_delete_file_success` | file removed |
| `test_delete_file_missing` | error string |
| `test_move_file_success` | file moved |
| `test_copy_file_success` | file copied |
| `test_run_file_python` | mocked subprocess, captures output |
| `test_run_file_timeout` | mocked timeout returns error |

### `tests/agents/test_file_agent.py`

7 tests mocking `call_llm` + individual tool functions (same pattern as `tests/agents/test_network_agent.py`):
- invalid JSON → fallback message
- unknown action → fallback message
- action `read` → calls `read_file`
- action `write` → calls `write_file`
- action `find` → calls `find_files`
- action `run` → calls `run_file`
- prior tool_results preserved in output

## Constraints

- No sandboxing — unrestricted filesystem access (process user permissions apply).
- No interactive input support for `run_file` — stdout/stderr capture only.
- `delete_file` does not recurse into non-empty directories (safety floor).
- All tool functions are synchronous; agent wraps in `asyncio.to_thread`.
