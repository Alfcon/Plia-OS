# Settings Inline Panel (Option B)

**Date:** 2026-06-18  
**Status:** Approved

## Goal

Replace the modal overlay for Settings with an inline slide-in panel that appears between the left sidebar and the chat area. The left sidebar (Settings + Exit buttons, agent log) remains visible and interactive at all times.

## Layout

```
┌──────────────┬──────────┬────────────────┬───────────────┐
│ ⚙ Settings   │ Voice  ● │  Engine        │               │
│              │ Web      │  ┌──────────┐  │               │
│ ⏻ Exit       │ Agents   │  │ Kokoro ▾│  │  chat area    │
│              │ LLM      │  └──────────┘  │               │
│ [agent log]  │ System   │  Voice         │               │
│              │ Reminders│  ┌──────────┐  │               │
│              │ Calendar │  │af_heart▾│  │               │
│              │ Memory   │  └──────────┘  │               │
│              │ Modules  │                │               │
│              │ Home     │  [Apply]       │               │
└──────────────┴──────────┴────────────────┴───────────────┘
  130px fixed    120px nav   ~380px content   shrinks/grows
```

## Behavior

- Clicking ⚙ Settings in the left sidebar opens the panel (slides in, chat shrinks right).
- Clicking ⚙ Settings again collapses the panel (chat expands back).
- Escape key collapses the panel.
- Chat area remains interactive while the panel is open (no backdrop/overlay).
- Default section on open: Voice.

## Structure Changes

### Remove
- `#menu-overlay` wrapper div and its backdrop
- `#menu-footer` (Settings + Exit buttons already in `#left-sidebar`)
- `#menu-header` (Plia-OS title + close button — no longer needed)
- `openMenu()` / `closeMenu()` / `_menuKeyHandler` logic tied to the overlay

### Add / Rename
- `#settings-panel` — new inline flex column, hidden by default (`width: 0; overflow: hidden`)
  - CSS transition on `width` (0 → 500px) for slide effect
  - Contains existing `#m-nav` and `#m-content` unchanged
- `#app-body` (already exists) — flex row: `#left-sidebar` | `#settings-panel` | chat area

### Update
- `openSettings()` → toggles `.open` class on `#settings-panel` (sets width, shows content)
- `sb-settings-btn` active state when panel is open
- Escape key listener attached/detached on panel open/close
- Remove the redundant `toggleMenuSettings()` function

## CSS

```css
#settings-panel {
  width: 0;
  overflow: hidden;
  transition: width 0.2s ease;
  display: flex;
  flex-direction: row;
  background: #111;
  border-right: 1px solid #2a2a2a;
  flex-shrink: 0;
}
#settings-panel.open {
  width: 500px;
}
```

## What Does NOT Change

- `#m-nav`, `#m-content`, `.m-pane`, `.m-nav-btn` — all section content unchanged
- `showMenuSection()`, all apply functions — unchanged
- Left sidebar width (130px), buttons, agent log — unchanged
- All API calls, config logic — unchanged

## Success Criteria

- Clicking ⚙ Settings slides in the panel; clicking again collapses it.
- Chat area shrinks/grows smoothly with CSS transition.
- Escape closes the panel.
- All settings sections (Voice, Web, Agents, LLM, System, Reminders, Calendar, Memory, Modules, Home) function identically to current.
- No modal overlay or backdrop anywhere in the flow.
