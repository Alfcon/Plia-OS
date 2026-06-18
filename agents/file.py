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
