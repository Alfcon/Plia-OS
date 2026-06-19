# Agent Log Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `#agent-badges` and `#agent-log` from the hidden Agents settings tab into `#left-sidebar` so agent routing feedback is always visible.

**Architecture:** Pure HTML edits to one file (`dashboard/static/index.html`). No JS changes — the `agent_routing` WebSocket handler finds elements by `getElementById('agent-log')` and `querySelectorAll('.agent-badge')`, which work regardless of DOM position. No backend changes.

**Tech Stack:** HTML, CSS (inline and `<style>` block in `index.html`).

## Global Constraints

- Single file modified: `dashboard/static/index.html`
- No JS changes — do not touch any `<script>` block
- No new files
- No backend changes
- Sidebar width is 130px — badges must use `flex-wrap: wrap` and `justify-content: center`
- The Agents nav button and the Agents pane must both be removed together — removing only one would break `showMenuSection()` (which would throw on a missing button or missing pane)

---

### Task 1: Move agent badges and log to sidebar

**Files:**
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: existing `#agent-badges`, `#agent-log`, `.agent-badge` — IDs and classes must not change (JS depends on them)
- Produces: same elements in `#left-sidebar`; Agents settings tab removed

There are no automated tests for dashboard HTML. Verification is: run the Python suite to confirm no regressions, then open the browser and manually verify.

- [ ] **Step 1: Remove the dead `#m-agent-badges` CSS rule**

Find and delete this exact line from the `<style>` block (currently line 109):

```
    #m-agent-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
```

This selector never matched anything — the element ID is `agent-badges`, not `m-agent-badges`. Removing it changes no visible behaviour.

- [ ] **Step 2: Remove the Agents nav button from `#m-nav`**

Find this exact line (currently line 695) and delete it:

```html
        <button class="m-nav-btn" data-section="agents" onclick="showMenuSection('agents')">Agents</button>
```

The surrounding buttons (`Web` above, `LLM` below) remain untouched. After this change `#m-nav` has 10 buttons instead of 11.

- [ ] **Step 3: Remove the Agents pane**

Find and delete this exact block (currently lines 924–934):

```html
        <!-- Agents pane -->
        <div id="m-section-agents" class="m-pane" style="display:none">
          <div id="agent-badges" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;">
            <span class="agent-badge" data-agent="memory">memory</span>
            <span class="agent-badge" data-agent="web">web</span>
            <span class="agent-badge" data-agent="code">code</span>
            <span class="agent-badge" data-agent="calendar">calendar</span>
            <span class="agent-badge" data-agent="home">home</span>
          </div>
          <div id="agent-log"></div>
        </div>
```

The `<div id="m-section-system" …>` that follows immediately after becomes the new first pane.

- [ ] **Step 4: Add agent section to `#left-sidebar`**

Find the closing `</div>` of `#left-sidebar` (currently line 145, immediately after the Exit button):

```html
  <button class="sb-exit-btn" onclick="exitApp()">⏻ Exit</button>
</div>
```

Replace with:

```html
  <button class="sb-exit-btn" onclick="exitApp()">⏻ Exit</button>
  <hr style="border:none;border-top:1px solid #2a2a2a;margin:4px 0;">
  <div style="font-size:0.65rem;color:#444;text-align:center;letter-spacing:0.05em;">agent</div>
  <div id="agent-badges" style="display:flex;flex-wrap:wrap;gap:3px;justify-content:center;">
    <span class="agent-badge" data-agent="memory">memory</span>
    <span class="agent-badge" data-agent="web">web</span>
    <span class="agent-badge" data-agent="code">code</span>
    <span class="agent-badge" data-agent="calendar">calendar</span>
    <span class="agent-badge" data-agent="home">home</span>
  </div>
  <div id="agent-log"></div>
</div>
```

The `id="agent-badges"` and `id="agent-log"` attributes are identical to those deleted in Step 3 — IDs are just moving DOM location.

- [ ] **Step 5: Update the docs text**

Find this exact paragraph (currently lines 353–354):

```html
      <h4>Agent Badges</h4>
      <p>The badges in <strong>Settings → Agents</strong> show which specialist handled the last turn. The top-bar badge also shows the active agent during processing. A badge lights up blue when active.</p>
```

Replace with:

```html
      <h4>Agent Badges</h4>
      <p>The badges in the <strong>left sidebar</strong> show which specialist handled the last turn. The top-bar badge also shows the active agent during processing. A badge lights up blue when active.</p>
```

- [ ] **Step 6: Run Python test suite — verify no regressions**

```bash
source .venv/bin/activate
pytest --tb=short -q
```

Expected: all 676 tests pass. The HTML change does not affect any Python test.

- [ ] **Step 7: Smoke-test in the browser**

Start the server:
```bash
source .venv/bin/activate && python core/main.py
```

Open `http://localhost:8000`. Verify:

- [ ] Page loads; sidebar shows 4 buttons + thin separator + "agent" label + 5 small badges + empty log
- [ ] Settings opens; Agents tab is gone from the left nav; Voice tab opens by default
- [ ] All remaining settings tabs (Voice, Web, LLM, System, Reminders, Calendar, Memory, Modules, Home, Permissions) open correctly
- [ ] Send a chat message; the correct agent badge highlights blue in the sidebar
- [ ] `→ agentname` entry appears in the sidebar log, newest at top, max 5 entries kept
- [ ] Send 6+ messages to different agents; log stays capped at 5 entries

- [ ] **Step 8: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): move agent badges and log from settings tab into sidebar"
```
