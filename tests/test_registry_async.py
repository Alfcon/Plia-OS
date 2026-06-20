import pytest
from core.registry import (
    ToolExecutionError,
    call_tool_async,
    register_tool,
    _tools,
    clear_tools,
)


# ToolExecutionError

def test_tool_execution_error_is_exception():
    e = ToolExecutionError("boom")
    assert isinstance(e, Exception)
    assert str(e) == "boom"


# register_tool

def test_register_tool_adds_entry():
    def fn(): return "ok"
    result = register_tool(
        name="my_fn",
        fn=fn,
        description="does a thing",
        parameters={"type": "object", "properties": {}},
    )
    assert result is True
    assert "my_fn" in _tools
    assert _tools["my_fn"]["fn"] is fn
    assert _tools["my_fn"]["schema"]["function"]["name"] == "my_fn"
    assert _tools["my_fn"]["schema"]["function"]["description"] == "does a thing"


def test_register_tool_collision_returns_false_and_leaves_original():
    def fn1(): return "first"
    def fn2(): return "second"
    register_tool(name="dup", fn=fn1, description="", parameters={})
    result = register_tool(name="dup", fn=fn2, description="", parameters={})
    assert result is False
    assert _tools["dup"]["fn"] is fn1   # original untouched


def test_register_tool_stores_module():
    def fn(): pass
    register_tool(name="t_mod", fn=fn, description="", parameters={}, module="mcp:fs")
    assert _tools["t_mod"]["module"] == "mcp:fs"


def test_register_tool_stores_meta():
    def fn(): pass
    meta = {"source": "mcp", "server": "fs", "tool": "read"}
    register_tool(name="t_meta", fn=fn, description="", parameters={}, meta=meta)
    assert _tools["t_meta"]["meta"] == meta


def test_register_tool_no_meta_field_when_none():
    def fn(): pass
    register_tool(name="t_nometa", fn=fn, description="", parameters={})
    assert "meta" not in _tools["t_nometa"]


# call_tool_async

async def test_call_tool_async_awaits_async_tool():
    async def async_fn(): return "async_result"
    register_tool(name="t_async", fn=async_fn, description="", parameters={})
    result = await call_tool_async("t_async", {})
    assert result == "async_result"


async def test_call_tool_async_calls_sync_tool():
    def sync_fn(): return "sync_result"
    register_tool(name="t_sync", fn=sync_fn, description="", parameters={})
    result = await call_tool_async("t_sync", {})
    assert result == "sync_result"


async def test_call_tool_async_passes_arguments():
    def add(x: int, y: int): return x + y
    register_tool(name="t_add", fn=add, description="", parameters={})
    result = await call_tool_async("t_add", {"x": 3, "y": 4})
    assert result == 7


async def test_call_tool_async_unknown_tool_raises_key_error():
    with pytest.raises(KeyError, match="Unknown tool"):
        await call_tool_async("does_not_exist", {})


async def test_call_tool_async_sync_tool_uses_to_thread():
    """Verify that sync tools are executed in thread pool via asyncio.to_thread."""
    from unittest.mock import AsyncMock, patch

    def sync_fn(x: int):
        return x * 2

    register_tool(name="t_sync_thread", fn=sync_fn, description="", parameters={})

    # Mock asyncio.to_thread to verify it's called
    with patch("core.registry.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = 42
        result = await call_tool_async("t_sync_thread", {"x": 21})

        # Verify asyncio.to_thread was called with the function and arguments
        mock_to_thread.assert_called_once_with(sync_fn, x=21)
        assert result == 42
