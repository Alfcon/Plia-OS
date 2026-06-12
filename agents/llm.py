import httpx
from core.config import get_config

_OLLAMA_TIMEOUT = 30.0


async def call_llm(messages: list[dict], tools: list | None = None) -> dict:
    config = get_config()
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            payload: dict = {
                "model": config.ollama_model,
                "messages": messages,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools
            resp = await client.post(f"{config.ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]
    except Exception as exc:
        if not config.fallback_provider:
            raise RuntimeError(
                f"Ollama failed and no fallback configured: {exc}"
            ) from exc
        return await _dispatch_fallback(messages, tools, config)


async def _dispatch_fallback(messages: list[dict], tools: list | None, config) -> dict:
    if config.fallback_provider == "openai":
        return await _call_openai(messages, tools, config)
    if config.fallback_provider == "anthropic":
        return await _call_anthropic(messages, tools, config)
    raise RuntimeError(f"Unknown fallback_provider: {config.fallback_provider!r}")


async def _call_openai(messages: list[dict], tools: list | None, config) -> dict:
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed. Run: pip install openai"
        ) from exc
    client = openai.AsyncOpenAI(api_key=config.fallback_api_key)
    kwargs: dict = {"model": config.fallback_model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0].message
    return {"role": "assistant", "content": choice.content or ""}


async def _call_anthropic(messages: list[dict], tools: list | None, config) -> dict:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        ) from exc
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    client = anthropic.AsyncAnthropic(api_key=config.fallback_api_key)
    kwargs: dict = {
        "model": config.fallback_model,
        "max_tokens": 1024,
        "messages": user_msgs,
    }
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    import anthropic as _anthropic
    text = next(
        (block.text for block in response.content if isinstance(block, _anthropic.types.TextBlock)),
        "",
    )
    return {"role": "assistant", "content": text}
