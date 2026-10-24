"""AirLLM backend — runs large HuggingFace models via layer sharding.

Install: pip install -e ".[airllm]"
Set airllm_model in config to a HuggingFace repo ID or local path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

_model = None
_model_id: str | None = None


def _get_model(model_id: str, compression: str):
    global _model, _model_id
    if _model is not None and _model_id == model_id:
        return _model
    try:
        from airllm import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "airllm not installed. Run: pip install -e '.[airllm]'"
        ) from exc

    logger.info("Loading AirLLM model %r (compression=%s) — this may take a moment", model_id, compression)
    kwargs: dict = {"max_seq_len": 2048}
    if compression != "none":
        kwargs["compression"] = compression
    _model = AutoModel.from_pretrained(model_id, **kwargs)
    _model_id = model_id
    logger.info("AirLLM model %r ready", model_id)
    return _model


def unload() -> None:
    """Release model from memory. Called when airllm_model config is cleared."""
    global _model, _model_id
    if _model is not None:
        logger.info("Unloading AirLLM model %r", _model_id)
        del _model
        _model = None
        _model_id = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def _build_prompt(model, messages: list[dict], tools: list | None) -> str:
    msgs = list(messages)
    if tools:
        tool_desc = json.dumps([t.get("function", t) for t in tools], indent=2)
        instruction = (
            "\n\nYou have access to these tools. To call one, respond ONLY with a JSON "
            "object with keys \"name\" and \"arguments\". If no tool is needed, respond normally.\n"
            f"Tools:\n{tool_desc}"
        )
        for i, m in enumerate(msgs):
            if m["role"] == "system":
                msgs[i] = {"role": "system", "content": m["content"] + instruction}
                break
        else:
            msgs.insert(0, {"role": "system", "content": instruction.strip()})

    try:
        return model.tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        parts = [f"{m['role'].upper()}: {m['content']}" for m in msgs]
        parts.append("ASSISTANT:")
        return "\n".join(parts)


def _extract_tool_call(text: str) -> dict | None:
    for pattern in (r"```json\s*(.*?)```", r"```\s*(.*?)```", r"(\{[^{}]+\})"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1).strip())
                if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                    return obj
            except (json.JSONDecodeError, KeyError):
                continue
    return None


def _generate_sync(messages: list[dict], tools: list | None, max_new_tokens: int) -> dict:
    from core.config import get_config
    cfg = get_config()
    model = _get_model(cfg.airllm_model, cfg.airllm_compression)
    prompt = _build_prompt(model, messages, tools)

    input_tokens = model.tokenizer(
        [prompt],
        return_tensors="pt",
        return_attention_mask=False,
        truncation=True,
        max_length=model.max_seq_len,
        padding=False,
    )

    generation_output = model.generate(
        input_tokens["input_ids"].cuda(),
        max_new_tokens=max_new_tokens,
        use_cache=True,
        return_dict_in_generate=True,
    )

    input_len = input_tokens["input_ids"].shape[1]
    new_tokens = generation_output.sequences[0][input_len:]
    response_text = model.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    if tools:
        tool_call = _extract_tool_call(response_text)
        if tool_call:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "airllm_0",
                    "type": "function",
                    "function": {
                        "name": tool_call["name"],
                        "arguments": json.dumps(tool_call["arguments"]),
                    },
                }],
            }

    return {"role": "assistant", "content": response_text}


async def call_llm_airllm(
    messages: list[dict],
    tools: list | None = None,
    max_new_tokens: int = 512,
) -> dict:
    return await asyncio.to_thread(_generate_sync, messages, tools, max_new_tokens)
