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


@tool(
    "Create a new custom agent. "
    "name: slug (lowercase letters, digits, hyphens only — e.g. 'mhd-research'). "
    "system_prompt: the agent's instructions. "
    "display_name: friendly label shown in lists (defaults to name). "
    "description: what this agent does, shown in list_custom_agents. "
    "tool_names: comma-separated tool names the agent may call (e.g. 'research_search,scrape_url'). "
    "keywords: comma-separated phrases that trigger this agent automatically (e.g. 'mhd,saltwater')."
)
def create_agent(
    name: str,
    system_prompt: str,
    display_name: str = "",
    description: str = "",
    tool_names: str = "",
    keywords: str = "",
) -> str:
    import re
    from core.agent_store import AgentDef
    from core.agent_store import save_agent as _save, get_agent as _get
    from core.supervisor import _reload_custom_agents

    if not re.match(r"^[a-z0-9-]+$", name):
        return "Name must be lowercase letters, digits, and hyphens only."
    if _get(name) is not None:
        return f"Agent '{name}' already exists. Use edit_agent to update it."

    tools_list = [t.strip() for t in tool_names.split(",") if t.strip()] if tool_names else []
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []

    defn = AgentDef(
        name=name,
        display_name=display_name or name,
        system_prompt=system_prompt,
        tool_names=tools_list,
        keywords=kw_list,
        llm_description=description,
    )
    try:
        _save(defn)
    except ValueError as exc:
        return str(exc)
    _reload_custom_agents()
    return f"Agent '{name}' created."


@tool(
    "Edit an existing custom agent. Only non-empty fields are updated — omit a field to keep the current value. "
    "name: the agent's slug (cannot be changed). "
    "system_prompt: replace the agent's instructions. "
    "display_name: replace the friendly label. "
    "description: replace the description shown in list_custom_agents. "
    "tool_names: comma-separated — replaces the full list. "
    "keywords: comma-separated — replaces the full list."
)
def edit_agent(
    name: str,
    display_name: str = "",
    description: str = "",
    system_prompt: str = "",
    tool_names: str = "",
    keywords: str = "",
) -> str:
    from core.agent_store import get_agent as _get, save_agent as _save
    from core.supervisor import _reload_custom_agents

    defn = _get(name)
    if defn is None:
        return f"No agent named '{name}'."

    if display_name:
        defn.display_name = display_name
    if description:
        defn.llm_description = description
    if system_prompt:
        defn.system_prompt = system_prompt
    if tool_names:
        defn.tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]
    if keywords:
        defn.keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    _save(defn)
    _reload_custom_agents()
    return f"Agent '{name}' updated."


@tool("Delete a custom agent by its slug name.")
def delete_agent(name: str) -> str:
    from core.agent_store import delete_agent as _delete
    from core.supervisor import _reload_custom_agents

    if not _delete(name):
        return f"No agent named '{name}'."
    _reload_custom_agents()
    return f"Agent '{name}' deleted."
