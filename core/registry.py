import inspect
from typing import Any, Callable, get_type_hints

_tools: dict[str, dict] = {}

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


def tool(description: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        name = fn.__name__
        if name in _tools:
            raise ValueError(f"Tool {name!r} already registered")
        _tools[name] = {
            "fn": fn,
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


def get_tool_schemas() -> list[dict]:
    return [entry["schema"] for entry in _tools.values()]


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name not in _tools:
        raise KeyError(f"Tool {name!r} not found")
    return _tools[name]["fn"](**arguments)


def list_tools() -> dict[str, str]:
    return {
        name: entry["schema"]["function"]["description"]
        for name, entry in _tools.items()
    }


def clear_tools() -> None:
    """For testing only."""
    _tools.clear()
