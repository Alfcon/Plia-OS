import pytest
import asyncio
from unittest.mock import patch


@pytest.fixture(autouse=True)
def clear_pending():
    from core import tool_guard
    tool_guard._pending.clear()
    yield
    tool_guard._pending.clear()


def test_respond_unknown_id():
    from core.tool_guard import respond
    assert respond("nonexistent-id", True) is False


def test_respond_known_id():
    from core.tool_guard import _PendingApproval, _pending, respond
    ap = _PendingApproval("mytool", {})
    _pending[ap.id] = ap

    result = respond(ap.id, True)
    assert result is True
    assert ap.approved is True
    assert ap._event.is_set()


@pytest.mark.asyncio
async def test_maybe_guard_unguarded_tool():
    with patch("core.tool_guard._is_guarded", return_value=False):
        from core.tool_guard import maybe_guard
        # Should complete without raising
        await maybe_guard("some_tool", {})


@pytest.mark.asyncio
async def test_maybe_guard_approved():
    from core.tool_guard import maybe_guard, _pending

    async def approve_async():
        await asyncio.sleep(0.01)
        for ap in list(_pending.values()):
            ap.resolve(True)

    with patch("core.tool_guard._is_guarded", return_value=True), \
         patch("core.events.emit", new=AsyncMock()):
        task = asyncio.create_task(approve_async())
        await maybe_guard("guarded_tool", {"arg": "val"})
        await task


@pytest.mark.asyncio
async def test_maybe_guard_denied_raises():
    from core.tool_guard import maybe_guard, _pending, ToolDeniedError

    async def deny_async():
        await asyncio.sleep(0.01)
        for ap in list(_pending.values()):
            ap.resolve(False)

    with patch("core.tool_guard._is_guarded", return_value=True), \
         patch("core.events.emit", new=AsyncMock()):
        task = asyncio.create_task(deny_async())
        with pytest.raises(ToolDeniedError):
            await maybe_guard("guarded_tool", {})
        await task


# Need AsyncMock
from unittest.mock import AsyncMock
