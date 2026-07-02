import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.config import reset_config
from core.supervisor import _supervisor_node
from core import events


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


@pytest.fixture(autouse=True)
def mock_memory(monkeypatch):
    mock = MagicMock()
    mock.recall.return_value = []
    monkeypatch.setattr("core.supervisor.get_memory_store", lambda: mock)
    return mock


async def test_run_turn_returns_string_and_messages():
    from core.supervisor import run_turn
    fake_msg = {"role": "assistant", "content": "It is 3pm."}
    with patch("core.supervisor.call_llm", new=AsyncMock(return_value=fake_msg)):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "What time is it?"},
        ])
    assert isinstance(text, str)
    assert len(text) > 0
    assert isinstance(history, list)


async def test_supervisor_routes_to_memory_then_responds():
    from core.supervisor import run_turn
    classify_msg = {"role": "assistant", "content": "memory"}
    respond_msg = {"role": "assistant", "content": "I remember your name."}
    call_count = 0

    async def fake_llm(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return classify_msg
        return respond_msg

    with patch("core.supervisor.call_llm", new=fake_llm):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "Do you remember my name?"},
        ])
    assert isinstance(text, str)


async def test_hop_limit_forces_response():
    from core.supervisor import run_turn
    classify_msg = {"role": "assistant", "content": "web"}
    respond_msg = {"role": "assistant", "content": "Here is what I found."}
    call_count = 0

    async def fake_llm(messages, tools=None):
        nonlocal call_count
        call_count += 1
        if call_count <= 6:
            return classify_msg
        return respond_msg

    with patch("core.supervisor.call_llm", new=fake_llm):
        text, history = await run_turn([
            {"role": "system", "content": "You are Plia."},
            {"role": "user", "content": "search everything forever"},
        ])
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_run_turn_auto_saves_turns(mock_memory):
    """After run_turn, both user and assistant turns are saved to the memory store."""
    from core.supervisor import run_turn
    messages = [
        {"role": "system", "content": "You are Plia."},
        {"role": "user", "content": "hello"},
    ]
    with patch("agents.llm.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = [
            {"message": {"role": "assistant", "content": "respond", "tool_calls": None}},
            {"message": {"role": "assistant", "content": "Hello there!", "tool_calls": None}},
        ]
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        response, _ = await run_turn(messages)

    add_turn_calls = mock_memory.add_turn.call_args_list
    roles = [c[0][0] for c in add_turn_calls]
    contents = [c[0][1] for c in add_turn_calls]
    assert "user" in roles
    assert "assistant" in roles
    assert "hello" in contents
    assert "Hello there!" in contents


@pytest.mark.asyncio
async def test_run_turn_injects_memory_context(mock_memory):
    """memory_context passed to AgentState comes from store.recall on the last user message."""
    from core.supervisor import run_turn
    mock_memory.recall.return_value = ["user: my name is Alfcon"]
    messages = [
        {"role": "system", "content": "You are Plia."},
        {"role": "user", "content": "what is my name"},
    ]

    captured_state = {}

    async def fake_invoke(state, *args, **kwargs):
        captured_state.update(state)
        return {
            "messages": state["messages"] + [{"role": "assistant", "content": "Alfcon"}],
            "tool_results": [],
        }

    with patch("core.supervisor._graph") as mock_graph:
        mock_graph.ainvoke = fake_invoke
        await run_turn(messages)

    assert "my name is Alfcon" in captured_state.get("memory_context", "")
    mock_memory.recall.assert_called_once_with("what is my name")


@pytest.mark.asyncio
async def test_supervisor_emits_agent_routing_for_specialist():
    captured = []
    async def capture(payload):
        captured.append(payload)

    events.subscribe(capture)
    try:
        state = {
            "messages": [{"role": "user", "content": "remember my name"}],
            "memory_context": "", "active_agent": None,
            "search_provider": "ddg", "hop_count": 0, "tool_results": [],
        }
        with patch("core.supervisor.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "memory"}
            await _supervisor_node(state)
    finally:
        events.unsubscribe(capture)

    routing = [e for e in captured if e["type"] == "agent_routing"]
    assert len(routing) == 1
    assert routing[0]["agent"] == "memory"


@pytest.mark.asyncio
async def test_supervisor_emits_for_respond():
    captured = []
    async def capture(payload):
        captured.append(payload)

    events.subscribe(capture)
    try:
        state = {
            "messages": [{"role": "user", "content": "hello"}],
            "memory_context": "", "active_agent": None,
            "search_provider": "ddg", "hop_count": 0, "tool_results": [],
        }
        with patch("core.supervisor.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "respond"}
            await _supervisor_node(state)
    finally:
        events.unsubscribe(capture)

    routing = [e for e in captured if e["type"] == "agent_routing"]
    assert len(routing) == 1
    assert routing[0]["agent"] == "respond"


@pytest.mark.asyncio
async def test_supervisor_does_not_emit_at_hop_limit():
    captured = []
    async def capture(payload):
        captured.append(payload)

    events.subscribe(capture)
    try:
        state = {
            "messages": [], "memory_context": "", "active_agent": None,
            "search_provider": "ddg", "hop_count": 5, "tool_results": [],
        }
        await _supervisor_node(state)
    finally:
        events.unsubscribe(capture)

    assert not any(e["type"] == "agent_routing" for e in captured)
