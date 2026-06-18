# Settings Inline Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the modal overlay for Settings with an inline slide-in panel that opens between the left sidebar and the chat area, leaving both always interactive.

**Architecture:** `#settings-panel` is a new `width: 0 → 500px` CSS-transition div inserted into the existing `#app-body` flex row. `openSettings()` becomes a toggle that adds/removes `.open` on the panel and `.active` on the sidebar button. The entire `#menu-overlay` DOM tree is removed.

**Tech Stack:** Vanilla JS, CSS transitions, single-file SPA (`dashboard/static/index.html`). No build step. No automated frontend tests — verification is manual via `python core/main.py`.

## Global Constraints

- All changes are in `dashboard/static/index.html` only.
- Do not touch any Python files.
- `#m-nav`, `#m-content`, `.m-pane`, `.m-nav-btn` IDs/classes must not change — they are referenced by `showMenuSection()` and apply functions throughout the file.
- All ten settings sections (voice/web/agents/llm/system/reminders/calendar/memory/modules/home) must remain functional.
- No new JS libraries or CSS frameworks.

---

### Task 1: CSS — remove modal styles, add inline panel styles

**Files:**
- Modify: `dashboard/static/index.html:74-96` (style block, modal/panel/footer rules)

**Interfaces:**
- Produces: `#settings-panel` CSS (width transition, `.open` state), `.sb-settings-btn.active` style

- [ ] **Step 1: Remove modal/overlay CSS rules**

In the `<style>` block (lines ~74–96), delete these rules entirely:

```css
/* DELETE all of these: */
#menu-overlay { position: fixed; inset: 0; z-index: 100; display: none; }
#menu-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.75); }
#menu-panel { position: absolute; left: 0; top: 0; bottom: 0; width: 633px; background: #111; border-right: 1px solid #2a2a2a; display: flex; flex-direction: column; }
#menu-header { padding: 20px 16px 14px; border-bottom: 1px solid #1e1e1e; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
#menu-header .menu-title { font-size: 1rem; color: #e0e0e0; letter-spacing: 0.08em; text-transform: uppercase; }
#menu-header .menu-close { background: none; border: none; color: #555; font-size: 1rem; cursor: pointer; width: auto; padding: 2px 6px; }
#menu-header .menu-close:hover { color: #e0e0e0; background: #1a1a1a; }
#menu-settings { flex: 1; overflow: hidden; display: flex; flex-direction: row; min-height: 0; }
#menu-footer { padding: 14px 16px 20px; border-top: 1px solid #1e1e1e; display: flex; flex-direction: column; gap: 0; flex-shrink: 0; }
#menu-footer .settings-btn { background: #0d1b2a; color: #4fc3f7; border: 1px solid #1e3a5f; margin-bottom: 12px; }
#menu-footer .settings-btn:hover { background: #1e3a5f; }
#menu-footer .exit-btn { background: #1a0808; color: #ef9a9a; border: 1px solid #7f1d1d; }
#menu-footer .exit-btn:hover { background: #7f1d1d; }
```

Keep these rules unchanged (they style the nav/content inside the panel):

```css
#m-nav { width: 122px; border-right: 1px solid #1e1e1e; padding: 10px 0; display: flex; flex-direction: column; flex-shrink: 0; }
.m-nav-btn { background: none; border: none; border-left: 2px solid transparent; border-radius: 0; color: #555; font-size: 0.72rem; padding: 10px 0; cursor: pointer; width: 100%; text-align: center; }
.m-nav-btn:hover { color: #ccc; background: #181818; }
.m-nav-btn.active { color: #4fc3f7; border-left-color: #4fc3f7; background: #0d1b2a; }
#m-content { flex: 1; overflow-y: auto; padding: 12px 14px; }
.m-pane label { font-size: 0.78rem; color: #999; display: block; margin-bottom: 6px; }
.m-pane select, .m-pane input[type=range], .m-pane input[type=text], .m-pane input[type=password] { width: 100%; background: #1a1a1a; color: #e0e0e0; border: 1px solid #2a2a2a; border-radius: 4px; padding: 4px 6px; margin-bottom: 2px; }
.m-pane .apply-btn { margin-top: 8px; background: #1a1a2e; color: #4fc3f7; border: 1px solid #1e3a5f; border-radius: 4px; padding: 5px 10px; font-size: 0.78rem; cursor: pointer; width: 100%; }
.m-pane .apply-btn:hover { background: #1e3a5f; }
#m-agent-badges { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
```

- [ ] **Step 2: Add `#settings-panel` CSS in place of removed rules**

After the `#left-sidebar` rules (around line 65), add:

```css
#settings-panel { width: 0; overflow: hidden; transition: width 0.2s ease; display: flex; flex-direction: row; background: #111; border-right: 1px solid #2a2a2a; flex-shrink: 0; min-height: 0; }
#settings-panel.open { width: 500px; }
#left-sidebar .sb-settings-btn.active { background: #1e3a5f; color: #fff; }
```

- [ ] **Step 3: Verify the style block looks correct**

The relevant part of the `<style>` block should now read (in order):
- `body`, `#top-bar`, `#app-body`, `#chat-wrap` — layout
- `#left-sidebar`, `#left-sidebar .sb-settings-btn`, `#left-sidebar .sb-exit-btn`
- **`#settings-panel`**, **`#settings-panel.open`**, **`#left-sidebar .sb-settings-btn.active`**  ← new
- `#m-nav`, `.m-nav-btn`, `#m-content`, `.m-pane *`, `#m-agent-badges` — kept
- All other existing rules below

No modal/overlay/panel/header/footer CSS should remain.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "style(dashboard): replace modal CSS with inline settings-panel transition"
```

---

### Task 2: HTML — remove `#menu-overlay`, add `#settings-panel` inline

**Files:**
- Modify: `dashboard/static/index.html:101-546` (body structure)

**Interfaces:**
- Consumes: CSS from Task 1 (`#settings-panel`, `#settings-panel.open`)
- Produces: `#settings-panel` div in `#app-body` containing `#m-nav` and `#m-content`

- [ ] **Step 1: Remove the entire `#menu-overlay` block**

Delete lines 101–503 (the whole `<div id="menu-overlay">` ... `</div>` block). This removes:
- `#menu-backdrop`
- `#menu-panel` > `#menu-header`
- `#menu-panel` > `#menu-settings` > `#m-nav` and `#m-content` (you will re-add these)
- `#menu-panel` > `#menu-footer`

- [ ] **Step 2: Insert `#settings-panel` into `#app-body`**

`#app-body` currently contains just `#left-sidebar` and `#chat-wrap`. After `</div>` that closes `#left-sidebar` (line ~533), add the new `#settings-panel` div with `#m-nav` and `#m-content` moved inside it:

```html
<div id="settings-panel">
  <div id="m-nav">
    <button class="m-nav-btn active" data-section="voice" onclick="showMenuSection('voice')">Voice</button>
    <button class="m-nav-btn" data-section="web" onclick="showMenuSection('web')">Web</button>
    <button class="m-nav-btn" data-section="agents" onclick="showMenuSection('agents')">Agents</button>
    <button class="m-nav-btn" data-section="llm" onclick="showMenuSection('llm')">LLM</button>
    <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system');loadPipelineStatus();loadSystemStats()">System</button>
    <button class="m-nav-btn" data-section="reminders" onclick="showMenuSection('reminders');loadReminders();loadTimers()">Reminders</button>
    <button class="m-nav-btn" data-section="calendar" onclick="showMenuSection('calendar');loadCalendar();loadGcalStatus()">Calendar</button>
    <button class="m-nav-btn" data-section="memory" onclick="showMenuSection('memory');loadMemory()">Memory</button>
    <button class="m-nav-btn" data-section="modules" onclick="showMenuSection('modules');loadModules()">Modules</button>
    <button class="m-nav-btn" data-section="home" onclick="showMenuSection('home');loadHassEntities()">Home</button>
  </div>
  <div id="m-content">
    <!-- PASTE the full #m-content innerHTML here, taken verbatim from the deleted #menu-overlay block -->
    <!-- This is every <div id="m-section-*" class="m-pane"> block for all 10 sections -->
  </div>
</div>
```

> The `#m-content` inner HTML (all `.m-pane` divs) is large (~370 lines). Copy it verbatim from what you deleted in Step 1 — do not retype it. Every `id="m-section-voice"` through `id="m-section-home"` div must be present.

- [ ] **Step 3: Verify `#app-body` structure**

`#app-body` should now contain exactly three direct children in this order:
1. `<div id="left-sidebar">` — Settings + Exit buttons + agent log
2. `<div id="settings-panel">` — m-nav + m-content (width: 0 by default)
3. `<div id="chat-wrap">` — conversation + input bar

No `#menu-overlay` div should exist anywhere in the document.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "refactor(dashboard): move settings from modal overlay to inline panel"
```

---

### Task 3: JS — replace modal open/close with inline toggle

**Files:**
- Modify: `dashboard/static/index.html` (script block, ~lines 2048–2072)

**Interfaces:**
- Consumes: `#settings-panel` (Task 2), `.sb-settings-btn` (existing), `showMenuSection()` (existing), `_syncMenuInputs()` (existing)
- Produces: `openSettings()` (toggle), `closeSettings()` (Escape handler target)

- [ ] **Step 1: Replace `openMenu`, `closeMenu`, `openSettings`, `toggleMenuSettings` functions**

Find and replace this entire block (~lines 2048–2072):

```javascript
// REMOVE:
function openMenu() {
  document.getElementById('menu-overlay').style.display = 'block';
  _syncMenuInputs();
  document.addEventListener('keydown', _menuKeyHandler);
}
function openSettings() {
  openMenu();
  document.getElementById('menu-settings').style.display = 'flex';
  showMenuSection('voice');
}
function closeMenu() {
  document.getElementById('menu-overlay').style.display = 'none';
  document.removeEventListener('keydown', _menuKeyHandler);
}
function _menuKeyHandler(e) { if (e.key === 'Escape') closeMenu(); }

function toggleMenuSettings() {
  const s = document.getElementById('menu-settings');
  if (s.style.display === 'none') {
    s.style.display = 'flex';
    showMenuSection('voice');
  } else {
    s.style.display = 'none';
  }
}
```

Replace with:

```javascript
function closeSettings() {
  document.getElementById('settings-panel').classList.remove('open');
  document.querySelector('.sb-settings-btn').classList.remove('active');
  document.removeEventListener('keydown', _menuKeyHandler);
}
function openSettings() {
  const panel = document.getElementById('settings-panel');
  if (panel.classList.contains('open')) {
    closeSettings();
  } else {
    panel.classList.add('open');
    document.querySelector('.sb-settings-btn').classList.add('active');
    showMenuSection('voice');
    _syncMenuInputs();
    document.addEventListener('keydown', _menuKeyHandler);
  }
}
function _menuKeyHandler(e) { if (e.key === 'Escape') closeSettings(); }
```

- [ ] **Step 2: Verify no dead references remain**

Search the script block for any remaining calls to `openMenu`, `closeMenu`, `toggleMenuSettings`, or `menu-overlay`. There should be none. Run:

```bash
grep -n "openMenu\|closeMenu\|toggleMenuSettings\|menu-overlay\|menu-settings" dashboard/static/index.html
```

Expected output: no matches (or only inside comments).

- [ ] **Step 3: Smoke-test the UI**

Start the server:
```bash
source .venv/bin/activate && python core/main.py
```
Open `http://localhost:8000`. Verify:
- [ ] Page loads, chat works
- [ ] Click ⚙ Settings → panel slides in from the left, chat shrinks right
- [ ] Settings button in sidebar shows active/highlighted state
- [ ] Click ⚙ Settings again → panel collapses, chat expands
- [ ] Press Escape while panel open → panel closes
- [ ] Each nav tab (Voice/Web/Agents/LLM/System/Reminders/Calendar/Memory/Modules/Home) shows correct content
- [ ] Apply buttons in each section still work (check Voice apply sends a config request in the network tab)
- [ ] ⏻ Exit button still works (shows confirm dialog)

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): settings opens as inline sidebar panel, no modal"
```
