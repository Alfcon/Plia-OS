# Agent Log Sidebar Design

**Date:** 2026-06-19
**Status:** Approved

## Overview

Move `#agent-badges` and `#agent-log` from the Agents settings tab into `#left-sidebar` so agent routing feedback is always visible without opening the settings panel.

## Changes

All changes are in `dashboard/static/index.html`. No JS changes required — the `agent_routing` WebSocket handler locates elements by `document.getElementById('agent-log')` and `document.querySelectorAll('.agent-badge')`, which work regardless of DOM position.

### 1. Remove from settings panel

Delete `#m-section-agents` (the Agents pane div and all its contents) from the settings panel content area.

Delete the "Agents" nav button from `#m-nav`:
```html
<button class="m-nav-btn" data-section="agents" onclick="showMenuSection('agents')">Agents</button>
```

`showMenuSection('agents')` would throw if called with the button and pane removed, but the button is the only caller — removing both together means the function is never called with `'agents'`.

### 2. Add to sidebar

Below the Exit button in `#left-sidebar`, add a thin separator and the agent section:

```html
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
```

The sidebar is 130px wide. Badges use `flex-wrap: wrap; justify-content: center` so they wrap naturally. Existing `.agent-badge` CSS (0.75rem, `padding: 3px 8px`) fits the sidebar width.

### 3. Update docs text

Line 354 currently reads:
> "The badges in **Settings → Agents** show which specialist handled the last turn."

Change to:
> "The badges in the **left sidebar** show which specialist handled the last turn."

### 4. Remove dead CSS

Remove the unused `#m-agent-badges` rule (the element ID is `agent-badges`, never `m-agent-badges`):
```css
#m-agent-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
```

## No changes needed

- `.agent-badge`, `.agent-badge.active` CSS — unchanged, same selectors
- `#agent-log`, `#agent-log div`, `#agent-log div.recent` CSS — unchanged
- All JS — unchanged (`getElementById`/`querySelectorAll` work by ID/class, not DOM position)
- All other settings tabs — unchanged

## Testing

- Open dashboard; badges and log visible in sidebar without touching settings
- Send a chat message; the agent badge for the routed agent highlights blue
- Log entry `→ agentname` appears below badges, newest first, max 5 entries
- Open Settings; Agents tab is gone from nav; remaining tabs unaffected
- `showMenuSection('agents')` call (if triggered by old bookmarks/muscle memory) does not throw
