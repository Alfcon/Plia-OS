import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _cfg(vision_model="llava", ollama_url="http://localhost:11434"):
    c = MagicMock()
    c.vision_model = vision_model
    c.ollama_url = ollama_url
    return c


def _fake_client(resp):
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_describe_image_bytes_returns_content():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"message": {"content": "A red cube."}})
    client = _fake_client(resp)
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("httpx.AsyncClient", return_value=client):
        from agents.vision import describe_image_bytes
        out = await describe_image_bytes(b"PNGDATA", "What is this?")
    assert out == "A red cube."
    sent = client.post.call_args.kwargs["json"]
    assert sent["model"] == "llava"
    assert sent["messages"][0]["images"]  # base64 image attached


@pytest.mark.asyncio
async def test_describe_image_bytes_no_model_returns_hint():
    with patch("core.config.get_config", return_value=_cfg(vision_model="")):
        from agents.vision import describe_image_bytes
        out = await describe_image_bytes(b"x", "q")
    assert "vision model" in out.lower()
    assert "ollama pull" in out.lower()


@pytest.mark.asyncio
async def test_describe_image_bytes_404_returns_pull_hint():
    import httpx
    resp = MagicMock()
    resp.status_code = 404

    def _raise():
        raise httpx.HTTPStatusError("not found", request=MagicMock(), response=resp)

    resp.raise_for_status = _raise
    client = _fake_client(resp)
    with patch("core.config.get_config", return_value=_cfg(vision_model="llava")), \
         patch("httpx.AsyncClient", return_value=client):
        from agents.vision import describe_image_bytes
        out = await describe_image_bytes(b"x", "q")
    assert "ollama pull llava" in out.lower()
