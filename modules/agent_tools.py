from __future__ import annotations

import json

from core.registry import tool


@tool("List all saved workflows with their names and step counts.")
def list_workflows() -> str:
    from agents.workflow_store import list_workflows as _list
    workflows = _list()
    if not workflows:
        return "No workflows defined."
    lines = [f"- {wf['name']}: {len(wf.get('steps', []))} step(s)" for wf in workflows]
    return "\n".join(lines)


@tool("Run a saved workflow by name. Optionally pass a JSON object as payload "
      "(e.g. '{\"input\": \"hello\"}') to supply variables like {{payload.input}}. "
      "Returns the final step result or an error message.")
async def run_workflow(name: str, payload_json: str = "") -> str:
    from agents.workflow_store import run_workflow as _run, get_workflow
    if get_workflow(name) is None:
        return f"No workflow named '{name}'. Use list_workflows to see available workflows."
    payload: dict | None = None
    if payload_json.strip():
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            return f"Invalid payload JSON: {exc}"
    output = await _run(name, payload=payload)
    if not output:
        return f"Workflow '{name}' produced no output."
    last = output[-1]
    if last.get("error"):
        return f"Workflow '{name}' failed at step {last['step']}: {last['error']}"
    return last.get("result", "")


@tool("List all custom agents with their names and descriptions.")
def list_custom_agents() -> str:
    from core.agent_store import list_agents
    agents = [a for a in list_agents() if a.enabled]
    if not agents:
        return "No custom agents defined."
    lines = []
    for a in agents:
        label = a.display_name or a.name
        desc = a.llm_description or "(no description)"
        wf = f" → workflow:{a.workflow_name}" if a.workflow_name else ""
        lines.append(f"- {a.name} ({label}){wf}: {desc}")
    return "\n".join(lines)


@tool("Run a custom agent by name with a message. "
      "The agent uses its own system prompt and tools to respond. "
      "Use list_custom_agents first to see available agents.")
async def run_agent(name: str, message: str) -> str:
    from core.agent_store import get_agent
    from core.registry import get_tool_schemas, call_tool_async

    defn = get_agent(name)
    if defn is None:
        return f"No agent named '{name}'. Use list_custom_agents to see available agents."
    if not defn.enabled:
        return f"Agent '{name}' is disabled."

    # Workflow-backed agent: delegate to workflow
    if defn.workflow_name:
        from agents.workflow_store import run_workflow as _run, get_workflow
        if get_workflow(defn.workflow_name) is None:
            return f"Agent '{name}' references missing workflow '{defn.workflow_name}'."
        output = await _run(defn.workflow_name, payload={"input": message})
        if not output:
            return f"Agent '{name}' (workflow) produced no output."
        last = output[-1]
        if last.get("error"):
            return f"Agent '{name}' failed: {last['error']}"
        return last.get("result", "")

    # LLM-backed agent: call LLM with agent's system prompt + allowed tools
    from agents.llm import call_llm
    all_schemas = get_tool_schemas()
    allowed = set(defn.tool_names)
    tools = [s for s in all_schemas if s["function"]["name"] in allowed] if allowed else []

    messages = [
        {"role": "system", "content": defn.system_prompt},
        {"role": "user", "content": message},
    ]
    _TOOL_CALL_LIMIT = 10
    for _ in range(_TOOL_CALL_LIMIT):
        response = await call_llm(messages, tools=tools)
        tool_calls = response.get("tool_calls", [])
        if not tool_calls:
            return response.get("content", "")
        messages.append(response)
        for tc in tool_calls:
            fn = tc["function"]
            tool_name = fn["name"]
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if tool_name not in allowed:
                result = f"Tool '{tool_name}' not permitted for this agent."
            else:
                try:
                    result = await call_tool_async(tool_name, args)
                except Exception as exc:
                    result = f"Error: {exc}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
            })
    return "Agent reached tool call limit without a final response."
