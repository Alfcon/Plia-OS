from __future__ import annotations
import pytest
from core.config import get_config, update_config


def test_adaptation_config_defaults():
    cfg = get_config()
    assert cfg.adaptation_enabled is False  # default off
    assert cfg.adaptation_route_examples == 3
    assert cfg.adaptation_style_examples == 3
    assert cfg.adaptation_direct_threshold == 0.95
    assert cfg.adaptation_rephrase_threshold == 0.85


def test_adaptation_config_updatable():
    update_config(adaptation_enabled=True, adaptation_route_examples=5)
    cfg = get_config()
    assert cfg.adaptation_enabled is True
    assert cfg.adaptation_route_examples == 5


from unittest.mock import AsyncMock, MagicMock, patch
from core.supervisor import AgentState


def _state(text: str, **over) -> AgentState:
    base = dict(
        messages=[{"role": "user", "content": text}],
        memory_context="",
        active_agent=None,
        search_provider="ddg",
        hop_count=0,
        tool_results=[],
        direct_result="",
    )
    base.update(over)
    return AgentState(**base)


@pytest.fixture
def adaptation_on():
    update_config(adaptation_enabled=True)
    yield


@pytest.mark.asyncio
async def test_near_exact_exemplar_routes_directly_without_llm(adaptation_on):
    store = MagicMock()
    store.retrieve_intent_examples.return_value = [
        {"utterance": "hit the lamp", "intent": "home", "similarity": 0.97}
    ]
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock(side_effect=AssertionError("LLM must not be called"))):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("hit the lamp please"))
    assert out["active_agent"] == "home"


@pytest.mark.asyncio
async def test_below_threshold_exemplars_become_few_shot_pairs(adaptation_on):
    store = MagicMock()
    store.retrieve_intent_examples.return_value = [
        {"utterance": "hit the lamp", "intent": "home", "similarity": 0.7}
    ]
    llm = AsyncMock(return_value={"content": "home"})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("zap the lamp"))

    assert out["active_agent"] == "home"
    sent = llm.call_args[0][0]
    assert sent[0]["role"] == "system"
    assert sent[1] == {"role": "user", "content": "hit the lamp"}
    assert sent[2] == {"role": "assistant", "content": "home"}
    assert sent[3] == {"role": "user", "content": "zap the lamp"}
    # Guards the a388b85 fix: only the live utterance + exemplar pairs.
    assert len(sent) == 4


@pytest.mark.asyncio
async def test_bogus_exemplar_intent_cannot_route(adaptation_on):
    store = MagicMock()
    store.retrieve_intent_examples.return_value = [
        {"utterance": "x", "intent": "not_a_real_intent", "similarity": 0.99}
    ]
    llm = AsyncMock(return_value={"content": "respond"})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("zzz qqq vvv"))
    assert out["active_agent"] == "respond"


@pytest.mark.asyncio
async def test_store_failure_does_not_break_routing(adaptation_on):
    with patch("agents.adaptation.get_adaptation_store", side_effect=RuntimeError("boom")), \
         patch("core.supervisor.call_llm", new=AsyncMock(return_value={"content": "web"})):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("zzz qqq vvv"))
    assert out["active_agent"] == "web"


@pytest.mark.asyncio
async def test_disabled_never_touches_store():
    # adaptation_enabled defaults to False here (no adaptation_on fixture).
    store = MagicMock()
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=AsyncMock(return_value={"content": "web"})):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("zzz qqq vvv"))
    assert out["active_agent"] == "web"
    store.retrieve_intent_examples.assert_not_called()


@pytest.mark.asyncio
async def test_keyword_route_still_wins_over_adaptation(adaptation_on):
    store = MagicMock()
    with patch("agents.adaptation.get_adaptation_store", return_value=store):
        from core.supervisor import _supervisor_node
        out = await _supervisor_node(_state("Thank you."))
    assert out["active_agent"] == "respond"
    store.retrieve_intent_examples.assert_not_called()


def _style_msgs(sent):
    return [m for m in sent if m.get("role") == "system"
            and "preferred style" in (m.get("content") or "")]


@pytest.mark.asyncio
async def test_style_examples_injected_on_freeform_path(adaptation_on):
    store = MagicMock()
    store.retrieve_style_examples.return_value = [
        {"utterance": "what's the time", "response": "3pm.", "similarity": 0.8}
    ]
    llm = AsyncMock(return_value={"content": "4pm.", "tool_calls": None})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm), \
         patch("core.supervisor.get_tool_schemas", return_value=[]):
        from core.supervisor import _respond_node
        await _respond_node(_state("what's the time now"))

    sent = llm.call_args[0][0]
    msgs = _style_msgs(sent)
    assert len(msgs) == 1
    assert "what's the time → 3pm." in msgs[0]["content"]


@pytest.mark.asyncio
async def test_style_skipped_on_tool_results_passthrough(adaptation_on):
    # THE GUARDRAIL: verbatim tool output must never be restyled.
    store = MagicMock()
    store.retrieve_style_examples.return_value = [
        {"utterance": "x", "response": "y", "similarity": 0.9}
    ]
    llm = AsyncMock(return_value={"content": "ok", "tool_calls": None})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm), \
         patch("core.supervisor.get_tool_schemas", return_value=[]):
        from core.supervisor import _respond_node
        await _respond_node(_state("q", tool_results=["Sunny, 22C."]))

    assert _style_msgs(llm.call_args[0][0]) == []
    store.retrieve_style_examples.assert_not_called()


@pytest.mark.asyncio
async def test_style_skipped_on_direct_result_passthrough(adaptation_on):
    store = MagicMock()
    llm = AsyncMock(side_effect=AssertionError("LLM must not be called"))
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm):
        from core.supervisor import _respond_node
        out = await _respond_node(_state("q", direct_result="verbatim tool output"))

    assert out["messages"][-1]["content"] == "verbatim tool output"
    store.retrieve_style_examples.assert_not_called()


@pytest.mark.asyncio
async def test_style_response_truncated(adaptation_on):
    store = MagicMock()
    store.retrieve_style_examples.return_value = [
        {"utterance": "u", "response": "z" * 500, "similarity": 0.8}
    ]
    llm = AsyncMock(return_value={"content": "ok", "tool_calls": None})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm), \
         patch("core.supervisor.get_tool_schemas", return_value=[]):
        from core.supervisor import _respond_node
        await _respond_node(_state("u"))

    content = _style_msgs(llm.call_args[0][0])[0]["content"]
    assert "z" * 200 in content
    assert "z" * 201 not in content


@pytest.mark.asyncio
async def test_no_style_message_when_no_examples(adaptation_on):
    store = MagicMock()
    store.retrieve_style_examples.return_value = []
    llm = AsyncMock(return_value={"content": "ok", "tool_calls": None})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm), \
         patch("core.supervisor.get_tool_schemas", return_value=[]):
        from core.supervisor import _respond_node
        await _respond_node(_state("u"))
    assert _style_msgs(llm.call_args[0][0]) == []


@pytest.mark.asyncio
async def test_style_disabled_never_touches_store():
    store = MagicMock()
    llm = AsyncMock(return_value={"content": "ok", "tool_calls": None})
    with patch("agents.adaptation.get_adaptation_store", return_value=store), \
         patch("core.supervisor.call_llm", new=llm), \
         patch("core.supervisor.get_tool_schemas", return_value=[]):
        from core.supervisor import _respond_node
        await _respond_node(_state("u"))
    assert _style_msgs(llm.call_args[0][0]) == []
    store.retrieve_style_examples.assert_not_called()


def test_direct_route_survives_corrupt_threshold(adaptation_on):
    # A null POSTed to /api/config (or a cleared UI number field) used to make
    # this raise TypeError straight into _supervisor_node, breaking the turn.
    update_config(adaptation_direct_threshold=None)
    from core.supervisor import _adaptation_direct_route
    examples = [{"utterance": "hit the lamp", "intent": "home", "similarity": 0.97}]
    assert _adaptation_direct_route(examples) is None
