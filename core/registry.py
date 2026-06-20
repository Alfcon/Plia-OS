import asyncio
import inspect
import logging
from typing import Any, Callable, get_type_hints

logger = logging.getLogger(__name__)

_tools: dict[str, dict] = {}
_LOADING_MODULE: str = ""

_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def _build_parameters(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        py_type = hints.get(name, str)
        properties[name] = {"type": _TYPE_MAP.get(py_type, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def set_loading_module(name: str) -> None:
    global _LOADING_MODULE
    _LOADING_MODULE = name


def tool(description: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        name = fn.__name__
        if name in _tools:
            raise ValueError(f"Tool {name!r} already registered")
        _tools[name] = {
            "fn": fn,
            "module": _LOADING_MODULE,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": _build_parameters(fn),
                },
            },
        }
        return fn
    return decorator


def _disabled_modules() -> set[str]:
    from core.config import get_config
    return set(get_config().disabled_modules)


def get_tool_schemas() -> list[dict]:
    disabled = _disabled_modules()
    return [
        entry["schema"] for entry in _tools.values()
        if entry["module"] not in disabled
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name not in _tools:
        raise KeyError(f"Tool {name!r} not found")
    entry = _tools[name]
    if entry["module"] in _disabled_modules():
        raise KeyError(f"Tool {name!r} is in a disabled module")
    return entry["fn"](**arguments)


def list_tools() -> dict[str, str]:
    return {
        name: entry["schema"]["function"]["description"]
        for name, entry in _tools.items()
    }


def list_modules() -> dict[str, list[str]]:
    """Returns {module_name: [tool_names]} for all registered tools."""
    result: dict[str, list[str]] = {}
    for name, entry in _tools.items():
        mod = entry["module"] or "unknown"
        result.setdefault(mod, []).append(name)
    return result


class ToolExecutionError(Exception):
    """Raised by tool wrappers (e.g. MCP) on execution failure."""


def register_tool(
    *,
    name: str,
    fn: Callable,
    description: str,
    parameters: dict,
    module: str = "",
    meta: dict | None = None,
) -> bool:
    """Register a tool by name. Returns False (logs warning) on collision."""
    if name in _tools:
        logger.warning("Tool %r already registered — skipped", name)
        return False
    entry: dict = {
        "fn": fn,
        "module": module,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    }
    if meta is not None:
        entry["meta"] = meta
    _tools[name] = entry
    return True


async def call_tool_async(name: str, arguments: dict) -> Any:
    """Async-capable tool dispatch. Awaits coroutine tools, runs sync tools in thread pool."""
    if name not in _tools:
        raise KeyError(f"Unknown tool: {name!r}")
    entry = _tools[name]
    if entry["module"] in _disabled_modules():
        raise KeyError(f"Tool {name!r} is in a disabled module")
    fn = entry["fn"]
    if inspect.iscoroutinefunction(fn):
        return await fn(**arguments)
    return await asyncio.to_thread(fn, **arguments)


def clear_tools() -> None:
    """For testing only."""
    _tools.clear()


def unregister_mcp_tools() -> None:
    """Remove all MCP-registered tools from the registry (called on MCP restart)."""
    to_remove = [
        name for name, entry in _tools.items()
        if entry.get("module", "").startswith("mcp:")
    ]
    for name in to_remove:
        del _tools[name]
