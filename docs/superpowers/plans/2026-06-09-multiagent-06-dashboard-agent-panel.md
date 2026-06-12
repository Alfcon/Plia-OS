# Dashboard Agent Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show live agent routing status in the dashboard sidebar — which specialist handled the last turn and a rolling log of the last 5 routing decisions.

**Architecture:** `core/supervisor.py` emits an `agent_routing` event on the existing event bus whenever the supervisor routes to a specialist agent (not "respond"). The dashboard WebSocket client handles this new event type to highlight the active agent badge and prepend to a small log. No new server endpoints needed — the existing WebSocket broadcast path carries the events automatically.

**Tech Stack:** Python asyncio events (existing `core/events.py`), plain JS in the existing dashboard HTML, pytest for supervisor unit tests.

---

## File Structure

```
core/supervisor.py          MOD  — import events, emit agent_routing after routing decision
tests/agents/test_supervisor.py  MOD  — 3 new tests for event emission
dashboard/static/index.html MOD  — CSS + HTML section + JS handler for agent_routing
```

---

### Task 1: supervisor emits agent_routing events

**Files:**
- Modify: `core/supervisor.py`
- Modify: `tests/agents/test_supervisor.py`

Context you need:
- `core/events.py` exports `emit(event_type: str, data: dict)` — async, broadcasts `{"type": event_type, **data}` to all subscribers.
- `_KNOWN_INTENTS = {"memory", "web", "code", "calendar", "home"}` — these are the specialist agents. "respond" is NOT in this set.
- The supervisor already does `logger.info("Supervisor routed to: %s", intent)` at line 50. Emit the event right after that line, only when `intent in _KNOWN_INTENTS`.
- Do NOT emit when routing to "respond" or when the hop limit forces a respond.

- [ ] **Step 1: Write the failing tests**

Append these 3 tests to `tests/agents/test_supervisor.py`:

```python
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
async def test_supervisor_does_not_emit_for_respond():
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
    assert len(routing) == 0


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
```

The test file already imports `pytest`, `AsyncMock`, `patch`. Add these to the existing import block at the top of the file:

```python
from core.supervisor import _supervisor_node
from core import events
```

Check what's already imported first — only add what's missing.

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_supervisor.py::test_supervisor_emits_agent_routing_for_specialist tests/agents/test_supervisor.py::test_supervisor_does_not_emit_for_respond tests/agents/test_supervisor.py::test_supervisor_does_not_emit_at_hop_limit -v 2>&1 | tail -15
```

Expected: 3 FAILED (no `agent_routing` events emitted yet).

- [ ] **Step 3: Update core/supervisor.py**

Add the import at the top of the file (after the existing imports):

```python
from core import events
```

Then in `_supervisor_node`, replace:

```python
    logger.info("Supervisor routed to: %s", intent)
    return {"active_agent": intent, "hop_count": state["hop_count"] + 1}
```

with:

```python
    logger.info("Supervisor routed to: %s", intent)
    if intent in _KNOWN_INTENTS:
        await events.emit("agent_routing", {"agent": intent})
    return {"active_agent": intent, "hop_count": state["hop_count"] + 1}
```

- [ ] **Step 4: Run the 3 new tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_supervisor.py::test_supervisor_emits_agent_routing_for_specialist tests/agents/test_supervisor.py::test_supervisor_does_not_emit_for_respond tests/agents/test_supervisor.py::test_supervisor_does_not_emit_at_hop_limit -v 2>&1 | tail -10
```

Expected: 3 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q 2>&1 | tail -3
```

Expected: all pass (≥167)

- [ ] **Step 6: Commit**

```bash
git add core/supervisor.py tests/agents/test_supervisor.py
git commit -m "feat: emit agent_routing event when supervisor routes to specialist"
```

---

### Task 2: dashboard agent panel

**Files:**
- Modify: `dashboard/static/index.html`

No automated tests — this is pure HTML/CSS/JS. Verify manually after editing.

The dashboard has:
- A `<style>` block at lines 7–39
- An `<aside>` sidebar starting at line 43
- A Status `<section>` at lines 61–64
- A `ws.onmessage` handler at lines 187–220

Make three changes:

- [ ] **Step 1: Add CSS for agent badges**

Inside the `<style>` block, before the closing `</style>` tag (after the last rule), add:

```css
    .agent-badge { padding: 3px 8px; border-radius: 3px; font-size: 0.75rem; display: inline-block; background: #1a1a1a; color: #555; border: 1px solid #333; }
    .agent-badge.active { background: #1e3a5f; color: #4fc3f7; border-color: #4fc3f7; }
    #agent-log { margin-top: 6px; }
    #agent-log div { padding: 2px 0; font-size: 0.75rem; color: #666; border-bottom: 1px solid #1a1a1a; }
    #agent-log div.recent { color: #aaa; }
```

- [ ] **Step 2: Add Agents panel HTML**

After the closing `</section>` of the Status block (line 64), insert:

```html
  <!-- Agents Panel -->
  <section>
    <h2>Agents</h2>
    <div id="agent-badges" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;">
      <span class="agent-badge" data-agent="memory">memory</span>
      <span class="agent-badge" data-agent="web">web</span>
      <span class="agent-badge" data-agent="code">code</span>
      <span class="agent-badge" data-agent="calendar">calendar</span>
      <span class="agent-badge" data-agent="home">home</span>
    </div>
    <div id="agent-log"></div>
  </section>
```

- [ ] **Step 3: Add agent_routing handler in ws.onmessage**

In the `ws.onmessage` handler, after the `if (msg.type === 'wake')` block, add:

```javascript
    if (msg.type === 'agent_routing') {
      document.querySelectorAll('.agent-badge').forEach(b => b.classList.remove('active'));
      const badge = document.querySelector(`.agent-badge[data-agent="${msg.agent}"]`);
      if (badge) badge.classList.add('active');
      const log = document.getElementById('agent-log');
      const entry = document.createElement('div');
      entry.className = 'recent';
      entry.textContent = `→ ${msg.agent}`;
      log.insertBefore(entry, log.firstChild);
      while (log.children.length > 5) log.removeChild(log.lastChild);
    }
```

- [ ] **Step 4: Verify the HTML is valid**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -c "
from pathlib import Path
html = Path('dashboard/static/index.html').read_text()
assert 'agent-badge' in html
assert 'agent_routing' in html
assert 'agent-log' in html
assert 'data-agent=\"memory\"' in html
assert 'data-agent=\"calendar\"' in html
print('HTML checks pass')
"
```

Expected: `HTML checks pass`

- [ ] **Step 5: Run full suite — confirm no regressions**

```bash
.venv/bin/python -m pytest --tb=short -q 2>&1 | tail -3
```

Expected: all pass (≥167)

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add agent panel to dashboard with live routing badges and log"
```
