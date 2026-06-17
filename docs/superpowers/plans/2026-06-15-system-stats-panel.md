# System Stats Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CPU, RAM, disk, GPU, and VRAM model status display to the System sidebar section below the existing pipeline status panel.

**Architecture:** Pure frontend change — `GET /api/system/info` and `GET /api/vram/status` already exist and return all needed data. A new `loadSystemStats()` JS function fetches both in parallel and renders a stats list into `#sys-stats` div appended below the pipeline panel. Called on System nav click (alongside existing `loadPipelineStatus()`).

**Tech Stack:** Vanilla JS fetch (existing), `GET /api/system/info` (existing), `GET /api/vram/status` (existing)

---

## File Map

| File | Change |
|------|--------|
| `dashboard/static/index.html` | Add `#sys-stats` HTML below pipeline panel; extend System nav btn; add `loadSystemStats()` JS |

No new backend. No new tests (no new backend logic).

---

### Task 1: Add system stats panel to System section

**Files:**
- Modify: `dashboard/static/index.html`

**Context:**

`GET /api/system/info` returns:
```json
{
  "os": "Linux",
  "cpu_percent": 23.5,
  "cpu_count": 8,
  "ram_total_gb": 16.0,
  "ram_used_gb": 8.2,
  "disk_total_gb": 512.0,
  "disk_used_gb": 200.0,
  "vram_gb": 8.0,
  "gpu_name": "NVIDIA GeForce RTX 3080"
}
```
All numeric fields may be `null` if `psutil` is unavailable. `gpu_name` may be `null` if no GPU.

`GET /api/vram/status` returns:
```json
{
  "studio_mode": false,
  "active_heavy": null,
  "models": {
    "whisper": {"state": "cpu", "vram_gb": 0.0},
    "tts": {"state": "gpu", "vram_gb": 2.5}
  },
  "vram_used_gb": 2.5,
  "vram_total_gb": 8.0
}
```
`models` is a `{name: {state, vram_gb}}` dict. `state` is `"gpu"` or `"cpu"`.

`_esc(s)` is an existing JS helper at line 434 that HTML-escapes strings.

`#m-section-system` currently ends at line 300:
```html
        <div id="m-section-system" class="m-pane" style="display:none">
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:10px;">Voice Pipeline</div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="pipeline-state-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#555;flex-shrink:0;"></span>
              <span id="pipeline-state-label" style="font-size:0.78rem;color:#aaa;">—</span>
            </div>
            <button id="pipeline-toggle-btn" onclick="togglePipeline()"
              style="background:#1e1e1e;border:1px solid #333;border-radius:3px;color:#aaa;font-size:0.75rem;padding:3px 10px;cursor:pointer;">
              Stop
            </button>
          </div>
        </div>
```

System nav button currently at line 102:
```html
        <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system');loadPipelineStatus()">System</button>
```

`loadPipelineStatus()` and `togglePipeline()` are at lines ~553–587. `async function downloadHistory()` is immediately after them.

- [ ] **Step 1: Add `#sys-stats` HTML inside `#m-section-system`**

Find this exact block:
```html
        <div id="m-section-system" class="m-pane" style="display:none">
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:10px;">Voice Pipeline</div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="pipeline-state-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#555;flex-shrink:0;"></span>
              <span id="pipeline-state-label" style="font-size:0.78rem;color:#aaa;">—</span>
            </div>
            <button id="pipeline-toggle-btn" onclick="togglePipeline()"
              style="background:#1e1e1e;border:1px solid #333;border-radius:3px;color:#aaa;font-size:0.75rem;padding:3px 10px;cursor:pointer;">
              Stop
            </button>
          </div>
        </div>
```

Replace with:
```html
        <div id="m-section-system" class="m-pane" style="display:none">
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:10px;">Voice Pipeline</div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="pipeline-state-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#555;flex-shrink:0;"></span>
              <span id="pipeline-state-label" style="font-size:0.78rem;color:#aaa;">—</span>
            </div>
            <button id="pipeline-toggle-btn" onclick="togglePipeline()"
              style="background:#1e1e1e;border:1px solid #333;border-radius:3px;color:#aaa;font-size:0.75rem;padding:3px 10px;cursor:pointer;">
              Stop
            </button>
          </div>
          <hr style="border-color:#222;margin:10px 0;" />
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="font-size:0.78rem;color:#aaa;">System</span>
            <button onclick="loadSystemStats()" style="background:none;border:none;color:#4fc3f7;font-size:0.75rem;cursor:pointer;">↻ Refresh</button>
          </div>
          <div id="sys-stats" style="font-size:0.75rem;color:#888;">Loading…</div>
        </div>
```

- [ ] **Step 2: Extend System nav button to call `loadSystemStats()`**

Find this exact line:
```html
        <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system');loadPipelineStatus()">System</button>
```

Replace with:
```html
        <button class="m-nav-btn" data-section="system" onclick="showMenuSection('system');loadPipelineStatus();loadSystemStats()">System</button>
```

- [ ] **Step 3: Add `loadSystemStats()` JS function**

Find the `async function loadPipelineStatus()` function. Add `loadSystemStats()` immediately before it:

```javascript
  async function loadSystemStats() {
    const el = document.getElementById('sys-stats');
    if (!el) return;
    try {
      const [infoR, vramR] = await Promise.all([
        fetch('/api/system/info'),
        fetch('/api/vram/status'),
      ]);
      const info = infoR.ok ? await infoR.json() : {};
      const vram = vramR.ok ? await vramR.json() : {};
      const row = (label, val) =>
        `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #1a1a1a;">` +
        `<span>${label}</span><span style="color:#e0e0e0;">${val}</span></div>`;
      const rows = [];
      if (info.cpu_percent != null) rows.push(row('CPU', `${info.cpu_percent}% &times; ${info.cpu_count}`));
      if (info.ram_used_gb != null) rows.push(row('RAM', `${info.ram_used_gb} / ${info.ram_total_gb} GB`));
      if (info.disk_used_gb != null) rows.push(row('Disk', `${info.disk_used_gb} / ${info.disk_total_gb} GB`));
      if (info.gpu_name) rows.push(row('GPU', _esc(info.gpu_name)));
      if (vram.vram_total_gb) rows.push(row('VRAM', `${vram.vram_used_gb} / ${vram.vram_total_gb} GB`));
      const models = vram.models || {};
      const modelRows = Object.entries(models).map(([name, m]) => {
        const color = m.state === 'gpu' ? '#81c784' : '#555';
        return `<div style="display:flex;justify-content:space-between;padding:2px 0;">` +
          `<span style="color:#666;">${_esc(name)}</span>` +
          `<span style="color:${color};">${m.state}</span></div>`;
      });
      const modelSection = modelRows.length
        ? `<div style="margin-top:6px;font-size:0.72rem;color:#666;margin-bottom:3px;">VRAM models</div>${modelRows.join('')}`
        : '';
      el.innerHTML = rows.join('') + modelSection || '<span style="color:#555;">No data</span>';
    } catch(e) {
      el.textContent = 'Failed to load';
    }
  }

```

- [ ] **Step 4: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: 313 passed (no backend changed).

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add system stats panel to System section"
```

---

## Self-Review

**Spec coverage:**
- ✅ CPU (percent × count) — from `info.cpu_percent` and `info.cpu_count`
- ✅ RAM (used/total GB) — from `info.ram_used_gb` / `info.ram_total_gb`
- ✅ Disk (used/total GB) — from `info.disk_used_gb` / `info.disk_total_gb`
- ✅ GPU name — from `info.gpu_name` (skipped if null)
- ✅ VRAM used/total — from `vram.vram_used_gb` / `vram.vram_total_gb` (skipped if 0/null)
- ✅ VRAM models list — from `vram.models` dict; green = gpu, grey = cpu
- ✅ Null safety — all fields guarded with `!= null` / truthiness checks
- ✅ Refresh button calls `loadSystemStats()`
- ✅ Auto-loads on System nav click
- ✅ `_esc()` used for GPU name and model names (could contain arbitrary strings)

**Placeholder scan:** None.

**Type consistency:**
- `info.cpu_percent` / `info.cpu_count` — numbers from psutil, may be null → guarded ✅
- `vram.models` — `{name: {state, vram_gb}}` dict → `Object.entries()` ✅
- `_esc(name)` — `name` is a string key from models dict ✅
