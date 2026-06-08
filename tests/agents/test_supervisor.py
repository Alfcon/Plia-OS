import pytest
from unittest.mock import AsyncMock, patch
from core.config import reset_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


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
