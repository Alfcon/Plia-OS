import json
import re
import httpx
from core.config import get_config

_FENCE_RE_LANG = re.compile(r"```[a-zA-Z]+\n?(.*?)```", re.DOTALL)
_FENCE_RE_ANY = re.compile(r"```[a-zA-Z]*\n?(.*?)```", re.DOTALL)


def parse_llm_json(content: str | None) -> dict:
    text = (content or "").strip()
    # Two-pass: language-tagged fences first (immune to empty bare-fence ambiguity),
    # then bare fences (``` without a language tag).
    for pattern in (_FENCE_RE_LANG, _FENCE_RE_ANY):
        for m in pattern.finditer(text):
            inner = m.group(1).strip()
            if not inner:
                continue
            try:
                result = json.loads(inner)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue
    result = json.loads(text or "{}")
    if not isinstance(result, dict):
        return {}
    return result

_OLLAMA_TIMEOUT = 180.0


async def call_llm(messages: list[dict], tools: list | None = None) -> dict:
    config = get_config()
    if config.airllm_model:
        from agents.airllm_backend import call_llm_airllm
        return await call_llm_airllm(messages, tools)
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
            body = resp.json()
            _record_usage(body, config.ollama_model)
            return body["message"]
    except Exception as exc:
        if not config.fallback_provider:
            raise RuntimeError(
                f"Ollama failed and no fallback configured: {exc}"
            ) from exc
        return await _dispatch_fallback(messages, tools, config)


def _record_usage(body: dict, model: str) -> None:
    try:
        from core.token_usage import record
        prompt = body.get("prompt_eval_count") or 0
        completion = body.get("eval_count") or 0
        if prompt or completion:
            record(prompt, completion, model)
    except Exception:
        pass


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
    result: dict = {"role": "assistant", "content": choice.content or ""}
    if choice.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments or "{}"),
                },
            }
            for tc in choice.tool_calls
        ]
    return result


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format message list to Anthropic format.

    Handles tool role messages (→ tool_result user turns) and assistant
    messages with tool_calls (→ tool_use content blocks).
    """
    result = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m["role"] == "assistant":
            if m.get("tool_calls"):
                content: list = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    fn = tc["function"]
                    args = fn.get("arguments") or {}
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn["name"],
                        "input": args if isinstance(args, dict) else json.loads(args),
                    })
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": "assistant", "content": m.get("content") or ""})
        elif m["role"] == "tool":
            tool_results: list = []
            while i < len(messages) and messages[i]["role"] == "tool":
                t = messages[i]
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": t.get("tool_call_id", ""),
                    "content": t.get("content", ""),
                })
                i += 1
            result.append({"role": "user", "content": tool_results})
            continue
        else:
            result.append(m)
        i += 1
    return result


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
        "messages": _to_anthropic_messages(user_msgs),
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = [
            {
                "name": t.get("function", t)["name"],
                "description": t.get("function", t).get("description", ""),
                "input_schema": t.get("function", t).get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
            for t in tools
        ]
    response = await client.messages.create(**kwargs)
    text = ""
    tool_calls = []
    for block in response.content:
        if isinstance(block, anthropic.types.TextBlock):
            text = block.text
        elif isinstance(block, anthropic.types.ToolUseBlock):
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {"name": block.name, "arguments": block.input},
            })
    result: dict = {"role": "assistant", "content": text}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result
