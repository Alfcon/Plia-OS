# Dashboard Config Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Fallback LLM and Web Search sidebar sections to the dashboard so users can configure the multiagent system's cloud fallback provider and web search provider at runtime.

**Architecture:** The backend already exposes `POST /api/config` which accepts any `PliaConfig` key — no server changes needed. The dashboard gets two new `<section>` blocks in `<aside>` (before the existing Modules section), two new JS functions (`applyFallbackConfig`, `applyWebConfig`), and the existing page-load `fetch('/api/config')` block is extended to populate the new inputs. The Google-specific fields are hidden unless the google provider is selected.

**Tech Stack:** Plain HTML/CSS/JS (no frameworks), existing `POST /api/config` endpoint.

---

## File Structure

```
dashboard/static/index.html   MOD  — CSS + HTML sections + JS for fallback and web config
```

No Python changes, no new test files. Verification via Python string assertions on the HTML file + full pytest run for regression check.

---

### Task 1: Fallback LLM and Web Search controls

**Files:**
- Modify: `dashboard/static/index.html`

The file has these existing patterns to follow:
- Config controls call `applyVoiceConfig()` which POSTs to `/api/config` with `fetch`
- Page-load block at line ~262 calls `fetch('/api/config')` and populates inputs
- Sidebar `<aside>` ends with a Modules section at lines 179–184, just before `</aside>`

Make four changes to `dashboard/static/index.html`:

---

- [ ] **Step 1: Add CSS for the new sections**

Read the file to find the `</style>` closing tag. Add these rules immediately before it:

```css
    .config-row { display: flex; gap: 6px; align-items: flex-end; margin-top: 6px; }
    .config-row button { flex: 0 0 auto; width: auto; padding: 6px 10px; }
    #google-fields { margin-top: 4px; }
```

---

- [ ] **Step 2: Add Fallback LLM section HTML**

Find the `<!-- Modules -->` comment (just before the closing `</aside>`). Insert this block immediately before it:

```html
  <!-- Fallback LLM -->
  <section>
    <h2>Fallback LLM</h2>
    <label>Provider
      <select id="fallback-provider" onchange="applyFallbackConfig()">
        <option value="">None (local only)</option>
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
      </select>
    </label>
    <label style="margin-top:6px;">Model
      <input type="text" id="fallback-model" placeholder="e.g. gpt-4o" />
    </label>
    <label style="margin-top:6px;">API Key
      <input type="password" id="fallback-api-key" placeholder="sk-…" />
    </label>
    <div class="config-row">
      <button onclick="applyFallbackConfig()">Apply</button>
    </div>
  </section>

  <!-- Web Search -->
  <section>
    <h2>Web Search</h2>
    <label>Provider
      <select id="web-provider" onchange="onWebProviderChange()">
        <option value="ddg">DuckDuckGo</option>
        <option value="google">Google</option>
      </select>
    </label>
    <div id="google-fields" style="display:none;">
      <label style="margin-top:6px;">Google API Key
        <input type="password" id="google-api-key" placeholder="AIza…" />
      </label>
      <label style="margin-top:6px;">Search Engine ID (CX)
        <input type="text" id="google-cx" placeholder="cx…" />
      </label>
    </div>
    <div class="config-row">
      <button onclick="applyWebConfig()">Apply</button>
    </div>
  </section>

```

---

- [ ] **Step 3: Add JS functions**

Find the closing `</script>` tag. Add these functions immediately before it:

```javascript
  function applyFallbackConfig() {
    fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        fallback_provider: document.getElementById('fallback-provider').value,
        fallback_model: document.getElementById('fallback-model').value,
        fallback_api_key: document.getElementById('fallback-api-key').value,
      }),
    });
  }

  function onWebProviderChange() {
    const isGoogle = document.getElementById('web-provider').value === 'google';
    document.getElementById('google-fields').style.display = isGoogle ? '' : 'none';
  }

  function applyWebConfig() {
    fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        web_search_default: document.getElementById('web-provider').value,
        google_search_api_key: document.getElementById('google-api-key').value,
        google_search_cx: document.getElementById('google-cx').value,
      }),
    });
  }
```

---

- [ ] **Step 4: Extend page-load config population**

Find the block starting with `fetch('/api/config')` (around line 262). It calls `.then(cfg => {` and ends with `onEngineChange();` and `startVramPolling();`. Add these lines immediately before the `onEngineChange();` call:

```javascript
      document.getElementById('fallback-provider').value = cfg.fallback_provider || '';
      document.getElementById('fallback-model').value = cfg.fallback_model || '';
      if (cfg.fallback_api_key)
        document.getElementById('fallback-api-key').value = cfg.fallback_api_key;
      document.getElementById('web-provider').value = cfg.web_search_default || 'ddg';
      if (cfg.google_search_api_key)
        document.getElementById('google-api-key').value = cfg.google_search_api_key;
      if (cfg.google_search_cx)
        document.getElementById('google-cx').value = cfg.google_search_cx;
      onWebProviderChange();
```

---

- [ ] **Step 5: Verify the HTML changes**

```bash
cd /home/alfcon/Projects/Plia-OS && .venv/bin/python -c "
from pathlib import Path
html = Path('dashboard/static/index.html').read_text()
assert 'fallback-provider' in html, 'missing fallback-provider'
assert 'fallback-model' in html, 'missing fallback-model'
assert 'fallback-api-key' in html, 'missing fallback-api-key'
assert 'applyFallbackConfig' in html, 'missing applyFallbackConfig'
assert 'web-provider' in html, 'missing web-provider'
assert 'google-fields' in html, 'missing google-fields'
assert 'google-api-key' in html, 'missing google-api-key'
assert 'google-cx' in html, 'missing google-cx'
assert 'applyWebConfig' in html, 'missing applyWebConfig'
assert 'onWebProviderChange' in html, 'missing onWebProviderChange'
print('HTML checks pass')
"
```

Expected: `HTML checks pass`

---

- [ ] **Step 6: Run full suite — no regressions**

```bash
cd /home/alfcon/Projects/Plia-OS && .venv/bin/python -m pytest --tb=short -q 2>&1 | tail -3
```

Expected: 167 passed

---

- [ ] **Step 7: Commit**

```bash
cd /home/alfcon/Projects/Plia-OS && git add dashboard/static/index.html && git commit -m "feat: add fallback LLM and web search config controls to dashboard"
```
