# Plia-OS

A local AI voice assistant with a web dashboard and a multi-agent backend.

## How it works

1. **Wake word** — openwakeword listens for the wake phrase
2. **STT** — faster-whisper transcribes speech to text
3. **Agents** — a LangGraph supervisor routes the request to specialist agents
4. **TTS** — Kokoro, Chatterbox, or Dramabox speaks the response
5. **Dashboard** — full-width top bar with system metrics, media controls, menu-based settings, persistent chat history

## Requirements

- Python 3.11 or 3.12 — **not 3.13 or 3.14.** The pinned `numpy==1.26.4` ships wheels only for
  CPython 3.9–3.12 (NumPy added 3.13 support in 2.1), and the pinned `torch==2.6.0` /
  `torchaudio==2.6.0` / `torchvision==0.21.0` wheels only go up to CPython 3.13. So on 3.13
  `pip install -r requirements.txt` fails at numpy, and on 3.14 it fails at both.
- [Ollama](https://ollama.com) running locally with a model loaded (default: `llama3.2`)
- A microphone

## Install via venv

Create an isolated environment first (with venv):

```bash
python3.12 -m venv .plia-os
source .plia-os/bin/activate
```

Make sure the interpreter is Python 3.11 or 3.12 (see the version requirement above); an
environment built on 3.13 or 3.14 will fail to install the pinned dependencies.

## Install via conda

```bash
conda create -n plia-os python=3.11
```

It asks `Proceed ([y]/n)?` — press `y`. Once complete, activate the environment:

```bash
conda activate plia-os
```

Then, with the environment active:

```bash
pip install -r requirements.txt
pip install -e . --no-deps
```

`requirements.txt` pins all optional extras (cloud fallbacks, AirLLM, observer, MCP). To install
only the core dependencies instead:

```bash
pip install -e .
```

Optional extras (install individually as needed):

```bash
pip install -e ".[playwright]"          # web scraping
pip install -e ".[fallback-openai]"     # OpenAI fallback LLM
pip install -e ".[fallback-anthropic]"  # Anthropic fallback LLM
pip install -e ".[dramabox]"            # Dramabox TTS engine
pip install -e ".[airllm]"              # AirLLM (70B+ on 4 GB VRAM)
pip install -e ".[mcp]"                 # Model Context Protocol servers
pip install -e ".[tor]"                 # Tor network routing
pip install -e ".[observer]"            # Screen/keyboard activity tracking
pip install -e ".[dev]"                 # Test dependencies
```

## Run

```bash
python3 core/main.py
```

Dashboard at `http://localhost:8000`. Voice pipeline starts automatically; dashboard stays available even if pipeline fails to load.

## Dashboard

| Area | What's there |
|------|-------------|
| Top bar | Status badge, OS, CPU %, RAM, VRAM bar (clickable), Disk, Battery (% + time left / time to full on laptops), **media player** (track, ⏮▶⏭, volume) |
| Chat pane | Persistent conversation history, text input (Enter to send, Shift+Enter for newline), live output from long-running tools, clickable shortcuts to the relevant tool or permission panel |
| ☰ Menu → Voice | TTS engine, STT model, wake word, voice cloning, clip generation |
| ☰ Menu → LLM | Ollama model, AirLLM model picker + VRAM estimate, compression, fallback cloud provider, system prompt |
| ☰ Menu → Web | Web search provider and Google API keys |
| ☰ Menu → Agents | Live agent routing badges and log |
| ☰ Menu → System | CPU/RAM/GPU stats, pipeline start/stop, config export/import, tool modules list |
| ☰ Menu → Reminders | Pending reminders and timers |
| ☰ Menu → Calendar | Upcoming events, Google Calendar link |
| ☰ Menu → Memory | Stored facts viewer, search, notes |
| ☰ Menu → History | Conversation history viewer with search and expand |
| ☰ Menu → Modules | Enable/disable tool modules |
| ☰ Menu → MCP | Model Context Protocol server config |
| ☰ Menu → Home | Home Assistant entity list and toggles |
| ☰ Menu → Permissions | Readiness per system grant (sudoers file + tool level), one-click **Set tools to Admin**, copyable grant/revoke commands, tool guard list |
| ☰ Menu → News | DDG news search by topic, RSS feed reader |
| ☰ Menu → Network | Tor toggle, WiFi scan/connect, MAC randomise/restore, wireless tools |
| ☰ Menu → Cron | Scheduled tasks with presets, next-run display, `tool:` invocation |
| ☰ Menu → Tokens | LLM token usage and cost tracking |
| ☰ Menu → Briefing | Morning briefing config: section toggles, time, preview button |
| ☰ Menu → Docs | Document index: index directories, search chunks, manage sources |
| ☰ Menu → Email | IMAP account management, Gmail OAuth, connection test |
| ☰ Menu → Observer | Live app tracker, focus timeline, activity profile |
| ☰ Menu → Proactive | Proactive assistant enable/disable, quiet hours |
| 🔧 Tools | Two-level tool browser — category → subgroup, search box, destructive tools grouped last — with auto-generated parameter forms and full output |
| ☰ Exit | Graceful shutdown via SIGTERM |
| `?` key | Keyboard shortcuts overlay |

### Menus and deep links

Both menus are **two levels deep** (group → subgroup → item) and share one interaction model: item
counts on every header, a sticky search box, and collapsible sections.

- **🔧 Tools** groups tools by *function*, not by module filename, from a single map in
  `core/tool_taxonomy.py` (eight categories — Memory & Agents, Files & Code, Vision & Media,
  Comms & Schedule, Web & Research, Home & System, Network, Security & Privacy — and ~40
  subgroups). Every registered tool must have exactly one home; a tool added without one lands in
  *Uncategorised* and fails `tests/test_tool_taxonomy.py`. Destructive tools are listed last in
  their category and flagged, so **⚠ Wireless Testing** renders as a separate red block. A tool can
  override its home with `@tool("…", category="X", subgroup="Y")`.
- **☰ Settings** is organised into seven groups — Assistant, Integrations, Automation, Knowledge,
  System, Network, Studio — with subgroups and a filter box (`filterSettingsNav`) that searches
  every entry. Merged panes (Tokens, Logs, Notifications, Config History) load both halves.
- **Deep links:** `#tools`, `#settings` and `#settings/<section>` open a panel on load.
  `openToolPanelAt(name)` jumps straight to one tool's form, which is also what the in-chat
  shortcuts use ("Run: `install_wireless_tools`" opens it, "Settings → Permissions" opens the
  grant pane and flashes the right group).

### Administrator password prompts

When a tool needs root and sudo has no cached credentials (and no NOPASSWD rule
covers it), Plia opens a native **“Plia needs administrator access”** dialog on
the desktop (zenity, kdialog or yad). The password is typed into that dialog and
consumed by sudo directly — Plia never sees, buffers or stores it. Sudo's normal
timestamp means one prompt covers a burst of privileged actions (MAC changes,
monitor mode, CPU tuning, Tor, …). On a headless host, or if the dialog is
cancelled or times out after three minutes, the tool reports what it needed and
how to grant it.

## Permissions

A privileged tool needs **two independent gates** open, and ☰ Menu → Permissions
shows them separately so it is obvious which half is missing:

1. **System grant** — a sudoers file under `/etc/sudoers.d/` that lets the Plia
   user run only the exact commands a feature needs (`plia-mac`, `plia-wireless`,
   `plia-iwlwifi`, `plia-optimise`).
2. **Tool level** — the per-tool `Admin` / `User` setting in `config.tool_permissions`.

Each group shows **● Ready** only when both are satisfied (groups that need no
sudoers grant, like System Optimisation, mark the tool level as *not required*).
The grant check reports *why* it is not ready — `file missing`,
`cannot read <file> (permission denied)`, or `insecure mode 0666` (sudo ignores
world-writable sudoers files) — instead of a bare "Not granted".

- **Grant commands** are generated for the account actually running Plia
  (`getpass.getuser()`), not a hard-coded username, and open in a copyable modal.
- **Set tools to Admin** switches every tool in a group to `Admin` in one click.
- The pane **refreshes itself** when you come back to the tab (and every 15 s
  while it is visible and focused), so a grant installed from a terminal flips
  the badge to Ready without a page reload.

`GET /api/permissions` returns `{user, os_groups, tool_permissions, ready_count}`;
each group carries `granted`, `grant_state`, `admin_tools`, `admin_count`,
`all_admin` and `ready`.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus chat input |
| `/` (Tools panel open) | Focus the tool search box |
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Ctrl+K` | Open Tools panel |
| `Ctrl+,` | Open Settings panel |
| `Esc` | Close open panel |
| `Enter` | Allow tool call (tool guard modal) |
| `Esc` | Deny tool call (tool guard modal) |
| `?` | Keyboard shortcuts overlay |

## Agents

| Agent | What it does |
|-------|-------------|
| memory | Remembers and recalls facts (SQLite + ChromaDB) |
| web | Searches via DuckDuckGo, Google Custom Search, or Playwright scrape |
| code | Runs Python/shell in a sandboxed subprocess |
| calendar | Add, list, delete events in `~/.plia/calendar.ics` or Google Calendar |
| reminder | Persists reminders to SQLite, fires as dashboard notifications via background polling |
| home | Calls Home Assistant services and reads entity states |
| file | Reads, writes, lists, and searches local files |
| network | MAC randomisation, Tor routing, Wi-Fi scanning, connecting (reuses saved profiles), key recovery, and hidden-SSID reveal |
| weather | Current conditions and forecast via Open-Meteo |

## TTS Engines

| Engine | VRAM | Notes |
|--------|------|-------|
| Kokoro | ~0.4 GB | Default; fast, high quality |
| Chatterbox | ~2 GB | Voice cloning with reference audio |
| Dramabox | ~8.5 GB | Expressive long-form narration |

VRAM broker evicts lower-priority models automatically when switching engines.

## Chat History

All conversations persist to `data/chat_history.db` (SQLite). Loaded on every page refresh. The voice pipeline also reloads the last 20 messages on startup so context survives restarts. Clear via the ✕ button in the input bar or `DELETE /api/history`.

## Reminders

The `set_reminder` tool (available to the LLM) persists reminders to SQLite. A background loop polls every 30 seconds and fires overdue reminders as dashboard notifications via the WebSocket. Reminders survive restarts.

## Cron

Recurring scheduled tasks stored in `~/.plia/cron.db`. Messages can be plain text (announced via TTS) or `tool:tool_name` to invoke any registered tool directly. Dashboard shows next-run time relative to now. Expression presets available (Daily 8am, Weekdays 8am, Hourly, etc.).

## Document Index

`index_documents(directory, glob)` chunks files and stores embeddings in ChromaDB at `~/.plia/doc_index`. Supports `.txt`, `.md`, `.pdf`, `.docx`, `.json`, `.yaml`, `.csv`. Search via `query_documents(query)`. Manage indexed sources from ☰ Menu → Docs.

## Observer

When enabled, tracks foreground app focus durations and (optionally) screen OCR and keystrokes. Data stored in `~/.plia/observer.db`. Dashboard shows live current app, top-apps bar chart, focus timeline, and an AI-generated activity profile.

## Email

IMAP accounts configured in the dashboard (☰ Menu → Email). Each account has a **Test** button to verify connectivity without fetching messages (uses the IMAP STATUS command — fast even on large inboxes). Used by the morning briefing to surface unread counts.

## Morning Briefing

`morning_briefing()` tool assembles a spoken briefing from configurable sections: weather, today's reminders, calendar events, email unread counts, and news headlines. Configure from ☰ Menu → Briefing: choose sections, set news topic, location, and daily schedule time. **Preview** button runs the briefing live in the panel.

## Proactive Assistant

Background loop (configurable interval) that monitors memory, reminders, observer data, and email to surface proactive suggestions. Respects quiet hours. Managed via ☰ Menu → Proactive or `POST /api/proactive/enable`.

## AirLLM

Layer-by-layer inference for large models (~4 GB VRAM for 70B+). Configure from ☰ Menu → LLM → AirLLM: pick a HuggingFace model ID (autocomplete with 15 popular models), select compression (4bit/8bit/none), see live VRAM estimate, and apply. Unload button frees VRAM on demand.

## System Optimise

☰ Menu → **Optimise** holds two one-click actions (each also runs straight from the sidebar sub-button):

- **Reduce Memory Usage** — unloads every model resident on the GPU (including Ollama's, via `keep_alive: 0`), clears the LLM response and CUDA caches, runs garbage collection, and drops the OS page cache. Reports RAM before/after and exactly what was freed.
- **Reduce Power Consumption** — unloads GPU models and switches every CPU to the `powersave` governor and the `power` energy-performance preference. **↺ Restore performance settings** puts back the values saved before the switch.

Both are registered tools too (`reduce_memory_usage`, `reduce_power_consumption`, `restore_system_performance`), so you can ask in chat (*"reduce memory usage"*) or run them from 🔧 Tools → System.

The CPU and page-cache steps need root. Grant them once from ☰ Menu → Permissions → **System Optimisation** (it only allows `tee` on the CPU governor, energy preference and `drop_caches`). Without the grant the unprivileged steps still run, and the output lists which steps were skipped.

## WiFi

### Connect — no password for saved networks

Ask in chat or voice — no password needed for networks you've joined before:

- *"Connect to my wifi"* — reconnects to the strongest in-range network you've saved (no extra data).
- *"Connect to the `Home` network"* — joins a specific network, reusing its saved profile. Partial names work (`"connect to home"` matches `Home Network`).
- *"What wifi networks have I saved?"* — lists saved networks.

Under the hood this runs `nmcli device wifi connect <ssid>` so NetworkManager reuses the stored
credentials from your existing saved connections; a brand-new network still needs its password
once (`connect_wifi(ssid, password=...)`), after which it's saved and connects password-free.

`wifi_status` reports the **broadcast SSID**, not the NetworkManager profile name (a profile
called "Auto Home" can join the SSID "Home"), together with signal, security, channel, band and IP.
`list_saved_wifi` lists each network once even though NetworkManager keeps one profile per saved
network *per BSSID*. Scans show the band — `2.4 GHz`, `5 GHz` or `6 GHz` — derived from nmcli's
frequency when available, so a 6 GHz channel 5 is not mistaken for 2.4 GHz.

### Show the saved WiFi password

Ask *"what is my wifi password?"*, *"show the saved wifi password"* or *"find the password for
the wifi"* and Plia reads the key from NetworkManager's local profile with
`check_wifi_password` (`nmcli -s -g 802-11-wireless-security.psk`). It falls back to
`netpass --check-wifi` when nmcli has no saved key. The key never leaves the machine.

This is a local lookup, not an attack: the WiFi agent recognises these phrasings **before** the
LLM runs (`_is_saved_password_request`), so it works with the model offline, and it deliberately
never takes the `gain` path — *"get access to a network I don't have the password for"* still
goes through WPS/handshake recovery.

### Recover access without the password

When a network needs a password you don't have, Plia tries to obtain it automatically with
`gain_wifi_access(ssid)` — it accepts an **SSID or a BSSID**, and connects with the recovered key
when it succeeds:

1. **Pre-flight** — one all-channel monitor-mode scan confirms the BSSID is visible *and* has at
   least one associated client before anything is attacked. A WPA handshake only exists when a
   client connects, so an idle BSSID is reported with the channels/bands where clients actually
   are instead of a string of blind deauths.
2. **WPS** first — Pixie Dust (`-K 1`, ~90 s) then automatic PIN stages of 300 s, 900 s and
   1800 s back-to-back (≈52 min). Reaver's session file is kept in `<memory_dir>/wps/`, so a
   later run resumes the PIN progress; when the stages finish the dashboard asks whether to
   **extend** and accepts a budget in seconds (max 3600).
3. Falls back to **WPA handshake capture** — unicast deauth to the real client MACs (plus
   broadcast), `--deauth-rc`, then a passive window for clients that ignore deauth (802.11w/PMF).
4. **Crack** with rockyou.txt (60-minute budget) and a generated digits wordlist, then connect.

This runs automatically when `connect_wifi` finds a secured network with no saved profile and no
password. It requires the **Wireless Tools** permission group (☰ Menu → Permissions → **Set tools
to Admin**, then run the grant command) and `install_wireless_tools`.

The crack step needs the **rockyou** wordlist. Plia looks in the usual locations
(`/usr/share/wordlists/…`, `~/wordlists/…`) and auto-decompresses a `.gz` copy into
`<memory_dir>/wordlists/`. On Ubuntu/Mint/Debian there is no `wordlists` package (it's Kali-only),
so run the **`download_rockyou`** tool once (≈51 MB) — or let `install_wireless_tools` offer it.

### Capture, crack and diagnostics

- **Monitor mode is automatic.** `capture_handshake`, `attack_wps` and `gain_wifi_access` accept a
  *managed* interface: they start monitor mode with `airmon-ng`, stop NetworkManager/wpa_supplicant
  from reclaiming the adapter, and put it back into managed mode afterwards.
- **`capture_handshake(..., passive=true)`** skips deauth entirely and runs a 90-second passive
  window with a dashboard "turn your WiFi off and on now" countdown. Use it for PMF/802.11w
  clients, or when you control the client and prefer not to inject.
- **Injection-limited adapters are detected.** Cards on the `iwlwifi`/`iwlmvm` drivers can monitor
  but cannot inject frames, so Plia says so up front (with adapter suggestions) instead of
  reporting `aireplay-ng`'s silent 0/30 failures.
- **Failure messages are specific.** A capture is inspected with `tcpdump`: no packets at all means
  monitor mode isn't working; EAPOL/deauth counts distinguish "client ignored deauth" from
  "M2 reply missing" from "client never reconnected".
- **Wordlists are bounded.** `create_wordlist` supports 1–15 characters and mixed charsets, and
  refuses a keyspace above 50 million candidates instead of filling the disk. `crack_handshake_auto`
  streams `crunch` into `aircrack-ng` and writes no temp file.
- **Installs explain themselves.** `install_wireless_tools` runs `apt-get update` with retries and
  distinguishes "needs sudo" from "DNS is broken" in its failure text. Binaries are located in
  `/usr/sbin` too, so a GUI-launched Plia no longer reports the aircrack suite as missing.

> Only use on networks you own or have explicit permission to test.

### Reveal hidden SSIDs

Networks that don't broadcast their name show as `<hidden>` in a scan. `reveal_hidden_ssid()`
puts the adapter in monitor mode, deauths clients on **every** hidden network, and reports each
real SSID (via client reconnect + probe requests). Ask: *"Reveal the hidden networks."*

### Monitor mode

`start_monitor_mode(interface)` puts an adapter into monitor mode (🔧 Tools → Network → WiFi →
Start Monitor Mode). `airmon-ng` usually warns that NetworkManager/wpa_supplicant/avahi-daemon can
interfere by changing channels or forcing the card back to managed mode. Because killing them drops
the machine off the network, Plia does **not** do it automatically — instead the tool result shows a
**⚔ Kill interfering processes** button that runs `kill_interfering_processes()`
(`airmon-ng check kill`) only when you press it. Run `stop_monitor_mode` afterwards to restore
managed mode and restart NetworkManager.

## WiFi Dongle Switching

Tools for switching between the internal WiFi card and a USB WiFi dongle — useful for isolating driver-related system freezes (run for days on the dongle with the internal driver disabled). Run them from 🔧 Tools → Network → WiFi, by voice/chat, or via `POST /api/tools/run`.

| Tool | What it does | sudo grant |
|------|--------------|------------|
| `enable_wifi_dongle` | Marks the USB dongle managed, turns on autoconnect, brings it up | no |
| `disable_wifi_dongle` | Disconnects the dongle and turns off autoconnect | no |
| `internal_wifi_status` | Reports whether `iwlwifi` is blacklisted and currently loaded | no |
| `disable_internal_wifi` | Blacklists the internal driver (`iwlwifi`/`iwlmvm`) and rebuilds the initramfs so it never loads — **takes effect on reboot** | yes |
| `enable_internal_wifi` | Removes the blacklist, rebuilds the initramfs, and loads `iwlwifi` again | yes |
| `reactivate_internal_network` | Recovery for a disabled/missing internal card: removes the blacklist, rebuilds initramfs, unblocks rfkill, reloads `iwlwifi`/`iwlmvm`, brings the interface up and hands it to NetworkManager | yes |

The dongle is auto-detected as the USB WiFi interface (a `wlx…` device); pass an explicit `interface` only if you have more than one.

**Two ways to disable the internal card:**

- **Quick** — `disable_wifi_dongle` / `enable_wifi_dongle` toggle NetworkManager's use of a device without touching drivers. Instantly reversible, no reboot. Not sufficient for driver freeze testing (the driver stays loaded).
- **Full** — `disable_internal_wifi` blacklists the driver so it never loads. Required for freeze testing. Needs a reboot to take effect; `enable_internal_wifi` reverses it, and `reactivate_internal_network` performs the full recovery if the card has disappeared (rfkill, module reload, interface up, NetworkManager).

**Permission grant (full method only).** `disable_internal_wifi` / `enable_internal_wifi` / `reactivate_internal_network` run `sudo` (`tee`/`rm`/`update-initramfs`/`modprobe`/`rfkill`/`ip`/`nmcli`/`systemctl`), so they're gated behind the **Internal WiFi Blacklist** permission group. Enable it in ☰ Menu → Permissions (set the tools to Admin), then run the one-time grant command it shows to create `/etc/sudoers.d/plia-iwlwifi`. Revoke with `sudo rm /etc/sudoers.d/plia-iwlwifi`.

**Make the dongle reboot-ready.** Give the dongle its own saved NetworkManager profile so it can connect once the internal card is blacklisted:

```bash
nmcli connection add type wifi ifname <dongle-iface> con-name "Dongle <SSID>" ssid "<SSID>" \
  -- wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<password>" connection.autoconnect yes
```

Use `connection.autoconnect no` for manual connect — this avoids the dongle and the internal card both joining the network on a normal reboot. Bring it up on demand with `nmcli connection up "Dongle <SSID>"` (the password is saved, so no prompt).

**Full switch to the dongle:**

1. Ensure the dongle has a saved profile (above) and is plugged in.
2. Run `disable_internal_wifi`.
3. Reboot. The internal `iwlwifi` won't load; the dongle connects (automatically if its profile autoconnects, otherwise `nmcli connection up "Dongle <SSID>"`).

**Switch back:** run `enable_internal_wifi`, then reboot (or it loads on the next boot once the blacklist is gone). If the internal card is missing or still unavailable, run `reactivate_internal_network` — it removes the blacklist, rebuilds the initramfs, unblocks rfkill, reloads the driver and hands the interface to NetworkManager, without needing a reboot when it succeeds.

## Further Reading

| Guide | What's in it |
|-------|--------------|
| [network-tools.md](network-tools.md) | Reference for every network tool: module, parameters, permissions, and what it actually runs |
| [privacy-network-guide.md](privacy-network-guide.md) | Task-oriented walkthrough of the **Privacy & Network** tool category in plain language |
| [wifi-dongle-switching.md](wifi-dongle-switching.md) | Step-by-step internal-card ↔ USB-dongle switching on Linux Mint (AX211 / RTL8812AU) |
| [Documents/](Documents/README.md) | Offline manuals and upstream docs for the network apps Plia drives — nmcli, aircrack-ng, reaver, crunch, nmap, Tor, iptables, netpass |

## Configuration

All config in `core/config.py` as a `PliaConfig` dataclass, persisted to `~/.plia/config.json`. Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |
| `ollama_model` | `llama3.2` | Model for inference |
| `tts_engine` | `kokoro` | TTS engine: `kokoro`, `chatterbox`, `dramabox` |
| `stt_model_size` | `base` | Whisper model size |
| `wake_word_model` | `hey_jarvis` | Wake word (or path to custom `.onnx`) |
| `web_search_default` | `ddg` | Default search provider: `ddg`, `google` |
| `fallback_provider` | _(empty)_ | Cloud fallback: `openai` or `anthropic` |
| `airllm_model` | _(empty)_ | HuggingFace model ID for AirLLM |
| `airllm_compression` | `4bit` | AirLLM compression: `4bit`, `8bit`, `none` |
| `hass_url` | _(empty)_ | Home Assistant base URL |
| `hass_token` | _(empty)_ | Home Assistant long-lived access token |
| `gcal_credentials_file` | _(empty)_ | Path to Google OAuth credentials JSON |
| `observer_enabled` | `false` | Enable activity observer |
| `weather_location` | _(empty)_ | Default location for weather (e.g. `Berlin`) |
| `briefing_news_topic` | `breaking news` | News topic for morning briefing |
| `briefing_cron_enabled` | `false` | Auto-deliver briefing daily |
| `briefing_cron_time` | `07:00` | Daily briefing time (HH:MM) |
| `briefing_include_weather` | `true` | Include weather in briefing |
| `briefing_include_reminders` | `true` | Include reminders in briefing |
| `briefing_include_calendar` | `true` | Include calendar in briefing |
| `briefing_include_email` | `true` | Include email counts in briefing |
| `briefing_include_news` | `true` | Include news headlines in briefing |
| `tool_guard_list` | `[]` | Tools requiring user approval before execution |
| `memory_dir` | `~/.plia` | Memory DB, calendar ICS, and observer DB location |
| `disabled_modules` | `[]` | Module filenames to skip at load |

Settings can be changed live from the dashboard without restarting.

## API Endpoints

### Config & System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Current config |
| POST | `/api/config` | Update config fields |
| GET | `/api/system/info` | OS, CPU, RAM, VRAM, disk metrics |
| GET | `/api/system/capabilities` | Per-engine VRAM fit check |
| GET | `/api/modules` | Loaded tool modules |
| POST | `/api/modules/{name}/enable` | Enable a module |
| POST | `/api/modules/{name}/disable` | Disable a module |
| GET | `/api/tools` | Registered tools list |
| GET | `/api/tools/schemas` | Full tool JSON schemas |
| GET | `/api/tools/taxonomy` | Tools grouped category → subgroup for the Tools menu |
| POST | `/api/tools/run` | Run a tool by name with params |
| GET | `/api/permissions` | Grant readiness, tool levels and guard list |
| POST | `/api/permissions/tools` | Update tool permissions |
| GET | `/api/token-usage` | LLM token usage and cost |
| POST | `/api/token-usage/reset` | Reset token counters |

### Chat & History
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a text message to the agent |
| GET | `/api/history` | Chat history (`?n=100`) |
| DELETE | `/api/history` | Clear chat history |

### Voice & Pipeline
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/status` | Voice pipeline state |
| POST | `/api/pipeline/start` | Start voice pipeline |
| POST | `/api/pipeline/stop` | Stop voice pipeline |
| POST | `/api/voice/transcribe` | Transcribe audio upload |
| POST | `/api/start-recording` | Start browser mic recording |
| POST | `/api/stop-recording` | Stop browser mic recording |
| POST | `/api/upload-reference-audio` | Upload voice clone reference |
| POST | `/api/generate-chatterbox` | Synthesise WAV (Chatterbox) |
| POST | `/api/generate-dramabox` | Synthesise WAV (Dramabox) |

### Memory & Notes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory` | List stored facts |
| GET | `/api/memory/search` | Search facts (`?q=`) |
| POST | `/api/memory` | Store a fact |
| PUT | `/api/memory/{key}` | Update a fact |
| DELETE | `/api/memory/{key}` | Delete a fact |
| GET | `/api/notes` | List notes |
| POST | `/api/notes` | Create a note |
| PUT | `/api/notes/{key}` | Update a note |
| DELETE | `/api/notes/{key}` | Delete a note |

### Reminders & Cron
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/reminders` | List pending reminders |
| POST | `/api/reminders` | Create a reminder |
| DELETE | `/api/reminders/{id}` | Delete a reminder |
| GET | `/api/timers` | List active timers |
| DELETE | `/api/timers/{id}` | Delete a timer |
| GET | `/api/cron` | List cron jobs (includes `next_run`) |
| POST | `/api/cron` | Create a cron job |
| PATCH | `/api/cron/{name}` | Update a cron job |
| DELETE | `/api/cron/{name}` | Delete a cron job |

### Calendar
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/calendar` | List events |
| POST | `/api/calendar` | Create an event |
| DELETE | `/api/calendar/{uid}` | Delete an event |
| GET | `/api/calendar/google/status` | Google Calendar auth state |
| POST | `/api/calendar/google/auth` | Start Google OAuth flow |
| GET | `/api/calendar/google/callback` | Google OAuth callback |

### Documents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents/sources` | List indexed document sources |
| POST | `/api/documents/index` | Index a directory (`{directory, glob}`) |
| POST | `/api/documents/remove` | Remove a source (`{source}`) |
| POST | `/api/documents/search` | Semantic search (`{query, n_results}`) |

### News
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/news/search` | DDG news search (`{query, max_items}`) |
| POST | `/api/news/rss` | Fetch and parse RSS feed (`{url, max_items}`) |

### Media & Audio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/media/status` | Now-playing track and playback state |
| POST | `/api/media/{action}` | Transport control: `play`, `pause`, `next`, `previous`, `stop` |
| GET | `/api/media/volume` | Current volume and mute state |
| POST | `/api/media/volume` | Set volume (`{percent}`) |
| POST | `/api/media/mute` | Mute audio |
| POST | `/api/media/unmute` | Unmute audio |

### Email
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/email/accounts` | List email accounts |
| POST | `/api/email/accounts` | Add an email account |
| DELETE | `/api/email/accounts/{name}` | Remove an email account |
| POST | `/api/email/accounts/{name}/test` | Test IMAP connectivity |
| POST | `/api/email/accounts/{name}/auth` | Start Gmail OAuth flow |
| GET | `/api/email/accounts/{name}/callback` | Gmail OAuth callback |
| GET | `/api/email/accounts/{name}/status` | Gmail OAuth status |

### Network
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/network/wifi` | WiFi scan + current connection |
| GET | `/api/network/mac` | List network interface MACs |
| POST | `/api/network/mac/randomize` | Randomize MAC address |
| POST | `/api/network/mac/restore` | Restore original MAC address |

### Home Assistant & VRAM
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hass/entities` | List HASS entities |
| POST | `/api/hass/toggle/{entity_id}` | Toggle entity |
| GET | `/api/vram/status` | VRAM broker state |
| POST | `/api/vram/release` | Release a loaded model |

### AirLLM
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/airllm/status` | AirLLM load state and model ID |
| POST | `/api/airllm/unload` | Unload AirLLM model from VRAM |

### System Prompt
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/system-prompt/undo` | Revert system prompt |
| POST | `/api/system-prompt/reset` | Reset to default |

### Observer & Proactive
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/observer/status` | Observer state and profile preview |
| POST | `/api/observer/enable` | Enable observer |
| POST | `/api/observer/disable` | Disable observer |
| GET | `/api/observer/activity` | Top apps, timeline, profile (`?minutes=60`) |
| GET | `/api/proactive/status` | Proactive assistant state |
| POST | `/api/proactive/enable` | Enable proactive loop |
| POST | `/api/proactive/disable` | Disable proactive loop |

### Tor & Tool Guard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tor/status` | Tor routing state |
| POST | `/api/tor/enable` | Enable Tor |
| POST | `/api/tor/disable` | Disable Tor |
| POST | `/api/tool-guard/respond/{id}` | Approve/deny a pending tool call |

### MCP
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mcp/servers` | Connected MCP servers |
| GET | `/api/mcp/config` | MCP server config |
| PUT | `/api/mcp/config` | Update MCP server config |
| POST | `/api/mcp/restart` | Restart MCP connections |
| POST | `/api/mcp/servers/{name}/disable` | Disable an MCP server |

### WebSocket
| Method | Path | Description |
|--------|------|-------------|
| WS | `/ws` | Live events: `status`, `transcript`, `agent_routing`, `vram_status`, `reminder_fired`, `tool_guard_request`, `proactive_message` |

### Shutdown
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/shutdown` | Graceful shutdown |

## Tests

```bash
pip install -e ".[dev]"
pytest
pytest --tb=short -q          # terse output
pytest tests/test_foo.py -v   # single file
```

2695 tests, all passing.
