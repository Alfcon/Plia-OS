from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from core import events


@pytest.fixture()
def wf_path(tmp_path):
    with patch("agents.workflow_store._workflows_path", return_value=tmp_path / "wf.json"):
        yield


def test_setup_subscribes():
    from core.event_triggers import setup_event_triggers, _on_event
    setup_event_triggers()
    assert events.is_subscribed(_on_event)


@pytest.mark.asyncio
async def test_matching_event_fires_workflow(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("brief", [], "d", event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("reminder_fired", {"msg": "time"})
    mock_run.assert_called_once_with(
        "brief",
        payload={"type": "reminder_fired", "msg": "time"},
    )


@pytest.mark.asyncio
async def test_non_matching_event_ignored(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("brief", [], "d", event_trigger="reminder_fired")
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("status", {"state": "armed"})
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_exception_does_not_propagate(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("bad", [], "d", event_trigger="reminder_fired")
    with patch("agents.workflow_store.run_workflow", AsyncMock(side_effect=RuntimeError("boom"))):
        setup_event_triggers()
        await events.emit("reminder_fired", {})  # must not raise


@pytest.mark.asyncio
async def test_workflow_without_trigger_not_fired(wf_path):
    from agents.workflow_store import save_workflow
    from core.event_triggers import setup_event_triggers
    save_workflow("plain", [], "d")  # no event_trigger
    mock_run = AsyncMock(return_value=[])
    with patch("agents.workflow_store.run_workflow", mock_run):
        setup_event_triggers()
        await events.emit("reminder_fired", {})
    mock_run.assert_not_called()
