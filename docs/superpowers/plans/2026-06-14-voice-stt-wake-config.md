# Wake Word + STT Config in Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose wake word and STT configuration fields (`wake_word_model`, `wake_word_threshold`, `stt_model_size`, `stt_language`) as editable controls in the dashboard Voice section.

**Architecture:** No new backend needed — `POST /api/config` already accepts all four fields (they are standard `PliaConfig` fields). This is a pure frontend change: add HTML controls to the Voice section in `dashboard/static/index.html`, wire them into the existing `applyVoiceConfig()` save function, and populate them in the existing `fetch('/api/config')` config-load block on page startup.

**Tech Stack:** Vanilla HTML/JS (existing), `POST /api/config` (existing)

---

## File Map

| File | Change |
|------|--------|
| `dashboard/static/index.html` | Add Wake Word + STT controls to Voice section; extend `applyVoiceConfig()`; populate from config on load |

No new backend files. No new tests (no new backend logic — all four fields already pass through `update_config()` in existing config tests).

---

### Task 1: Add Wake Word + STT controls to dashboard Voice section

**Files:**
- Modify: `dashboard/static/index.html`

**Context:**

The Voice section (`#m-section-voice`) ends at line 201 with an Apply button, then closes at line 202:
```html
          <button class="apply-btn" onclick="applyVoiceConfig()">Apply</button>
        </div>
```

`applyVoiceConfig()` is at line 1018–1036. It reads TTS field values and POSTs them to `POST /api/config`.

The config-load block starts at line 529:
```javascript
fetch('/api/config')
  .then(r => r.json())
  .then(cfg => {
    document.getElementById('tts-engine').value = cfg.tts_engine;
    // ... more fields ...
    onWebProviderChange();
    onEngineChange();
```

The block ends around line 564 with `onEngineChange()`. New population lines go before `onWebProviderChange()` / `onEngineChange()` calls at the end of that block.

`PliaConfig` defaults:
- `wake_word_model: str = "hey_jarvis"`
- `wake_word_threshold: float = 0.5`
- `stt_model_size: str = "base"` — valid values: `tiny | base | small | medium | large`
- `stt_language: str = "en"`

---

- [ ] **Step 1: Add Wake Word + STT HTML controls to the Voice section**

Find this exact string in `dashboard/static/index.html`:
```html
          <button class="apply-btn" onclick="applyVoiceConfig()">Apply</button>
        </div>
        <!-- Web pane -->
```

Replace with:
```html
          <hr style="border-color:#333;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:6px;">Wake Word</div>
          <label>Model
            <input type="text" id="wake-word-model" value="hey_jarvis"
              style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#eee;padding:4px 6px;border-radius:3px;font-size:0.75rem;" />
          </label>
          <label>Threshold
            <div style="display:flex;align-items:center;gap:8px;">
              <input type="range" id="wake-threshold" min="0.1" max="1.0" step="0.05" value="0.5"
                oninput="document.getElementById('wake-threshold-val').textContent=parseFloat(this.value).toFixed(2)"
                style="flex:1;" />
              <span id="wake-threshold-val" style="font-size:0.75rem;color:#888;width:28px;text-align:right;">0.50</span>
            </div>
          </label>
          <hr style="border-color:#333;margin:10px 0;" />
          <div style="font-size:0.78rem;color:#aaa;margin-bottom:6px;">Speech Recognition</div>
          <label>Model Size
            <select id="stt-model-size">
              <option value="tiny">tiny — fastest, least accurate</option>
              <option value="base" selected>base — recommended</option>
              <option value="small">small</option>
              <option value="medium">medium</option>
              <option value="large">large — slowest, most accurate</option>
            </select>
          </label>
          <label>Language
            <input type="text" id="stt-language" value="en" placeholder="e.g. en, fr, de, zh"
              style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#eee;padding:4px 6px;border-radius:3px;font-size:0.75rem;" />
          </label>
          <button class="apply-btn" onclick="applyVoiceConfig()">Apply</button>
        </div>
        <!-- Web pane -->
```

- [ ] **Step 2: Add fields to `applyVoiceConfig()`**

Find this exact block in `applyVoiceConfig()`:
```javascript
    const payload = {
      tts_engine: document.getElementById('tts-engine').value,
      kokoro_voice: document.getElementById('kokoro-voice').value,
      kokoro_speed: parseFloat(document.getElementById('kokoro-speed').value),
      chatterbox_exaggeration: parseFloat(document.getElementById('cb-exag').value),
      chatterbox_cfg_weight: parseFloat(document.getElementById('cb-cfg').value),
      chatterbox_temperature: parseFloat(document.getElementById('cb-temp').value),
      chatterbox_seed: (() => { const v = document.getElementById('cb-seed').value.trim(); return v === '' ? null : parseInt(v, 10); })(),
      dramabox_cfg_scale: parseFloat(document.getElementById('db-cfg').value),
      dramabox_stg_scale: parseFloat(document.getElementById('db-stg').value),
      dramabox_seed: parseInt(document.getElementById('db-seed').value, 10),
    };
```

Replace with:
```javascript
    const payload = {
      tts_engine: document.getElementById('tts-engine').value,
      kokoro_voice: document.getElementById('kokoro-voice').value,
      kokoro_speed: parseFloat(document.getElementById('kokoro-speed').value),
      chatterbox_exaggeration: parseFloat(document.getElementById('cb-exag').value),
      chatterbox_cfg_weight: parseFloat(document.getElementById('cb-cfg').value),
      chatterbox_temperature: parseFloat(document.getElementById('cb-temp').value),
      chatterbox_seed: (() => { const v = document.getElementById('cb-seed').value.trim(); return v === '' ? null : parseInt(v, 10); })(),
      dramabox_cfg_scale: parseFloat(document.getElementById('db-cfg').value),
      dramabox_stg_scale: parseFloat(document.getElementById('db-stg').value),
      dramabox_seed: parseInt(document.getElementById('db-seed').value, 10),
      wake_word_model: document.getElementById('wake-word-model').value.trim() || 'hey_jarvis',
      wake_word_threshold: parseFloat(document.getElementById('wake-threshold').value),
      stt_model_size: document.getElementById('stt-model-size').value,
      stt_language: document.getElementById('stt-language').value.trim() || 'en',
    };
```

- [ ] **Step 3: Populate fields from config on page load**

Find this exact block near the end of the config-load `.then(cfg => { ... })` block:
```javascript
      onWebProviderChange();
      onEngineChange();
```

Add the population lines immediately before them:
```javascript
      if (cfg.wake_word_model) document.getElementById('wake-word-model').value = cfg.wake_word_model;
      if (cfg.wake_word_threshold !== undefined) {
        document.getElementById('wake-threshold').value = cfg.wake_word_threshold;
        document.getElementById('wake-threshold-val').textContent = parseFloat(cfg.wake_word_threshold).toFixed(2);
      }
      if (cfg.stt_model_size) document.getElementById('stt-model-size').value = cfg.stt_model_size;
      if (cfg.stt_language) document.getElementById('stt-language').value = cfg.stt_language;
      onWebProviderChange();
      onEngineChange();
```

- [ ] **Step 4: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: 306 passed (no regressions — no backend changed).

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add wake word and STT config controls to Voice section"
```

---

## Self-Review

**Spec coverage:**
- ✅ `wake_word_model` — text input with default `hey_jarvis`, populated from config, saved in `applyVoiceConfig()`
- ✅ `wake_word_threshold` — range slider 0.1–1.0 step 0.05, live value readout, populated from config, saved
- ✅ `stt_model_size` — select with all 5 valid options (tiny/base/small/medium/large), `base` pre-selected, populated from config
- ✅ `stt_language` — text input with default `en`, populated from config, saved
- ✅ Apply button triggers same `applyVoiceConfig()` as TTS fields — no extra button needed
- ✅ Empty `wake_word_model` falls back to `'hey_jarvis'`; empty `stt_language` falls back to `'en'`

**Placeholder scan:** None found.

**Type consistency:**
- `wake_word_threshold` → `parseFloat(...)` → sent as float — matches `PliaConfig.wake_word_threshold: float` ✅
- `stt_model_size` → string from select value — matches `PliaConfig.stt_model_size: str` with valid enum values ✅
- `wake_word_model` / `stt_language` → `.trim() || default` → string — matches `str` fields ✅
