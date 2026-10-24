from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch
from core.agent_store import AgentDef, list_agents, get_agent, save_agent, delete_agent


def _defn(**kwargs) -> AgentDef:
    defaults = dict(
        name="finance",
        display_name="Finance",
        system_prompt="You are a finance bot.",
        tool_names=["calculate"],
        keywords=["stock", "portfolio"],
        llm_description="Use for financial questions",
    )
    defaults.update(kwargs)
    return AgentDef(**defaults)


@pytest.fixture()
def store(tmp_path):
    with patch("core.agent_store._AGENTS_FILE", tmp_path / "custom_agents.json"):
        yield


def test_get_unknown_returns_none(store):
    assert get_agent("nope") is None


def test_save_and_get_round_trip(store):
    d = _defn()
    save_agent(d)
    result = get_agent("finance")
    assert result is not None
    assert result.name == "finance"
    assert result.display_name == "Finance"
    assert result.system_prompt == "You are a finance bot."
    assert result.tool_names == ["calculate"]
    assert result.keywords == ["stock", "portfolio"]
    assert result.llm_description == "Use for financial questions"
    assert result.enabled is True


def test_save_sets_created_at(store):
    save_agent(_defn())
    result = get_agent("finance")
    assert result.created_at != ""


def test_update_preserves_created_at(store):
    save_agent(_defn())
    first_ts = get_agent("finance").created_at
    updated = _defn(display_name="Finance Updated")
    save_agent(updated)
    assert get_agent("finance").created_at == first_ts
    assert get_agent("finance").display_name == "Finance Updated"


def test_list_agents_sorted(store):
    save_agent(_defn(name="zebra", display_name="Z"))
    save_agent(_defn(name="alpha", display_name="A"))
    names = [a.name for a in list_agents()]
    assert names == ["alpha", "zebra"]


def test_delete_returns_true(store):
    save_agent(_defn())
    assert delete_agent("finance") is True
    assert get_agent("finance") is None


def test_delete_missing_returns_false(store):
    assert delete_agent("nope") is False


def test_invalid_slug_raises(store):
    with pytest.raises(ValueError, match="invalid"):
        save_agent(_defn(name="Bad Name!"))


def test_list_empty(store):
    assert list_agents() == []


def test_workflow_name_roundtrips(store):
    save_agent(_defn(workflow_name="my-wf"))
    result = get_agent("finance")
    assert result.workflow_name == "my-wf"


def test_workflow_name_defaults_none(store):
    save_agent(_defn())
    result = get_agent("finance")
    assert result.workflow_name is None
