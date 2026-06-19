import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MCP_CONFIG = Path.home() / ".plia" / "mcp_servers.json"
_TOOL_TIMEOUT: int = 30

_exit_stack = AsyncExitStack()
_initialized: bool = False


@dataclass
class _MCPServer:
    session: Any
    healthy: bool = True
    tools: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started_at: float = field(default_factory=time.monotonic)


_servers: dict[str, _MCPServer] = {}
_disabled_servers: set[str] = set()
_restart_lock: asyncio.Lock = asyncio.Lock()


def _validate_configs(servers: list[dict]) -> None:
    seen: set[str] = set()
    for cfg in servers:
        name = cfg.get("name")
        if not name:
            raise ValueError(f"MCP server config missing 'name': {cfg!r}")
        if "__" in name:
            raise ValueError(f"MCP server name {name!r} must not contain '__'")
        if name in seen:
            raise ValueError(f"Duplicate MCP server name: {name!r}")
        cmd = cfg.get("command")
        if not cmd or not cmd[0]:
            raise ValueError(
                f"MCP server {name!r}: 'command' must be a non-empty list with a non-empty executable"
            )
        seen.add(name)


async def load_mcp_servers() -> None:
    global _initialized
    if _initialized:
        logger.warning("load_mcp_servers() called twice — skipping")
        return
    _initialized = True

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return

    if not _MCP_CONFIG.exists():
        return

    try:
        servers = json.loads(_MCP_CONFIG.read_text())
        _validate_configs(servers)
    except Exception:
        logger.warning("mcp_servers.json invalid — skipping MCP", exc_info=True)
        return

    for cfg in servers:
        name = cfg["name"]
        cmd = cfg["command"]
        env = cfg.get("env") or None
        try:
            params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=env)
            transport = await _exit_stack.enter_async_context(stdio_client(params))
            session = await _exit_stack.enter_async_context(ClientSession(*transport))
            await session.initialize()
            server = _MCPServer(session=session)
            _servers[name] = server
            await _register_tools(name, server)
            logger.info("MCP server %r connected (%d tools)", name, len(server.tools))
        except Exception:
            logger.warning("MCP server %r failed to start — skipped", name, exc_info=True)
            _disabled_servers.add(name)


async def shutdown_mcp_servers() -> None:
    await _exit_stack.aclose()


def get_mcp_status() -> list[dict]:
    if not _MCP_CONFIG.exists():
        return []
    try:
        servers = json.loads(_MCP_CONFIG.read_text())
    except Exception:
        return []
    now = time.monotonic()
    result = []
    for cfg in servers:
        name = cfg.get("name", "")
        if not name:
            continue
        if name in _disabled_servers:
            status = "disabled"
        elif name in _servers:
            status = "connected"
        else:
            status = "failed"
        srv = _servers.get(name)
        result.append({
            "name": name,
            "status": status,
            "tools": list(srv.tools) if srv else [],
            "uptime_seconds": (now - srv.started_at) if srv else None,
        })
    return result


def disable_mcp_server(name: str) -> bool:
    if not _MCP_CONFIG.exists():
        return False
    try:
        servers = json.loads(_MCP_CONFIG.read_text())
    except Exception:
        return False
    known = {cfg.get("name") for cfg in servers}
    if name not in known:
        return False
    _disabled_servers.add(name)
    if name in _servers:
        _servers[name].healthy = False
    return True


async def restart_mcp_servers() -> None:
    global _exit_stack, _initialized
    async with _restart_lock:
        await _exit_stack.aclose()
        _exit_stack = AsyncExitStack()
        _servers.clear()
        _disabled_servers.clear()
        _initialized = False
        await load_mcp_servers()


async def _register_tools(name: str, server: _MCPServer) -> None:
    from core.registry import ToolExecutionError, register_tool

    response = await server.session.list_tools()
    for t in response.tools:
        prefixed = f"{name}__{t.name}"

        schema = t.inputSchema
        if not isinstance(schema, dict):
            logger.warning(
                "MCP tool %r has invalid inputSchema (%r) — using empty schema",
                prefixed,
                type(schema).__name__,
            )
            schema = {"type": "object", "properties": {}}

        _n, _t = name, t.name

        async def _fn(_n: str = _n, _t: str = _t, **kwargs: Any) -> str:
            if _n in _disabled_servers:
                raise ToolExecutionError(f"MCP server {_n!r} is disabled after failure")
            async with _servers[_n].lock:
                try:
                    result = await asyncio.wait_for(
                        _servers[_n].session.call_tool(_t, kwargs),
                        timeout=_TOOL_TIMEOUT,
                    )
                    return (
                        "\n".join(c.text for c in result.content if hasattr(c, "text"))
                        or "Done."
                    )
                except asyncio.TimeoutError:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(
                        f"MCP server {_n!r} timed out after {_TOOL_TIMEOUT}s — marked unhealthy"
                    )
                except Exception as e:
                    _servers[_n].healthy = False
                    _disabled_servers.add(_n)
                    raise ToolExecutionError(
                        f"MCP server {_n!r} error on {_t!r}: {e}"
                    ) from e

        registered = register_tool(
            name=prefixed,
            fn=_fn,
            description=t.description or prefixed,
            parameters=schema,
            module=f"mcp:{name}",
            meta={"source": "mcp", "server": name, "tool": t.name},
        )
        if registered:
            server.tools.append(prefixed)
