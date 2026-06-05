import httpx
from core.config import get_config
from core.registry import get_tool_schemas, call_tool


async def run_turn(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Run one conversation turn against Ollama.
    Returns (response_text, full_updated_history).
    Executes tool calls in a loop until Ollama returns plain text.
    """
    config = get_config()
    tools = get_tool_schemas()
    history = list(messages)

    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            payload: dict = {
                "model": config.ollama_model,
                "messages": history,
                "stream": False,
            }
            if tools:
                payload["tools"] = tools

            response = await client.post(
                f"{config.ollama_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()

            msg = response.json()["message"]
            history.append(msg)

            if not msg.get("tool_calls"):
                return msg["content"], history

            for tc in msg["tool_calls"]:
                fn = tc["function"]
                try:
                    result = call_tool(fn["name"], fn.get("arguments") or {})
                except Exception as exc:
                    result = f"Error calling {fn['name']}: {exc}"
                history.append({"role": "tool", "content": str(result)})
