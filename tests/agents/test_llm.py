import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.config import reset_config, update_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


async def test_call_llm_uses_ollama():
    from agents.llm import call_llm
    fake_msg = {"role": "assistant", "content": "Hello"}
    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": fake_msg}
        mock_response.raise_for_status = MagicMock()
        instance.post = AsyncMock(return_value=mock_response)
        result = await call_llm([{"role": "user", "content": "hi"}])
    assert result == fake_msg


async def test_call_llm_falls_back_on_ollama_failure():
    from agents.llm import call_llm
    update_config(fallback_provider="openai", fallback_model="gpt-4o-mini", fallback_api_key="sk-test")
    fake_msg = {"role": "assistant", "content": "Fallback reply"}

    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=Exception("connection refused"))
        with patch("agents.llm._call_openai", new=AsyncMock(return_value=fake_msg)):
            result = await call_llm([{"role": "user", "content": "hi"}])
    assert result == fake_msg


async def test_call_llm_raises_when_no_fallback_configured():
    from agents.llm import call_llm
    with patch("agents.llm.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=Exception("connection refused"))
        with pytest.raises(RuntimeError, match="no fallback"):
            await call_llm([{"role": "user", "content": "hi"}])
