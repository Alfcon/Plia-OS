# Tor VPN — Design Spec

**Date:** 2026-06-20
**Feature:** System-wide Tor transparent proxy with voice/dashboard toggle, kill switch, and circuit monitoring.

---

## Goal

Route all system network traffic through the Tor anonymity network via iptables transparent proxying. Toggled by voice command or dashboard button. Kill switch blocks all traffic if Tor drops, with desktop notification and error report. Verified before confirming enabled.

## Known Limitation

Transparent proxying is not sufficient against malware with root access — a root exploit can bypass iptables rules entirely. For stronger isolation, use Whonix or Tails. This feature protects against accidental cleartext connections and DNS leaks from misconfigured software.

---

## Architecture

```
modules/tor_tools.py        ← @tool functions: enable_tor, disable_tor, tor_status
core/tor_manager.py         ← iptables + tor daemon + kill switch + monitor loop
core/config.py              ← tor_enabled: bool = False
core/supervisor.py          ← keyword routes in "respond" list
dashboard/static/index.html ← VPN/Tor toggle in Settings > Network
```

`tor_manager.py` owns all privileged operations. `tor_tools.py` is a thin wrapper. The monitor loop is a background asyncio task (same pattern as `run_reminder_loop`).

---

## tor Daemon Config

Appended to `/etc/tor/torrc` on first enable:

```
VirtualAddrNetwork 10.192.0.0/10
AutomapHostsOnResolve 1
SOCKSPort 9050
TransPort 9040
DNSPort 5353
ControlPort 9051
CookieAuthentication 1
```

- `VirtualAddrNetwork` + `AutomapHostsOnResolve` are required for `.onion` DNS resolution — without them DNS leaks are possible.
- `SOCKSPort 9050` is required for the post-enable verification step.
- `ControlPort 9051` + `CookieAuthentication 1` enables `stem` monitoring.

---

## iptables Rules

### Transparent proxy chain (applied on enable):

```
# Create dedicated chain
iptables -t nat -N PLIA_TOR

# Rule order matters — RETURN rules before REDIRECT
[1] iptables -t nat -A PLIA_TOR -m owner --uid-owner $TOR_UID -j RETURN
[2] iptables -t nat -A PLIA_TOR -d 127.0.0.0/8 -j RETURN
[3] iptables -t nat -A PLIA_TOR -d 192.168.0.0/16 -j RETURN
[4] iptables -t nat -A PLIA_TOR -d 10.0.0.0/8 -j RETURN
[5] iptables -t nat -A PLIA_TOR -p udp --dport 53 -j REDIRECT --to-ports 5353
[6] iptables -t nat -A PLIA_TOR -p tcp --syn -j REDIRECT --to-ports 9040

# Apply chain
iptables -t nat -A OUTPUT -j PLIA_TOR
```

### Kill switch (applied only when Tor circuits drop):

```
iptables -A OUTPUT -m owner --uid-owner $TOR_UID -j ACCEPT
iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
iptables -P OUTPUT DROP
```

### Disable (restore clearnet):

```
iptables -t nat -F PLIA_TOR
iptables -t nat -X PLIA_TOR
iptables -t nat -D OUTPUT -j PLIA_TOR
iptables -F OUTPUT          # flush kill switch rules if active
iptables -P OUTPUT ACCEPT   # restore default policy
```

---

## tor UID Detection

Tor runs as different users per distro:

- Debian/Ubuntu: `debian-tor`
- Arch/Fedora: `tor`
- Some systems: numeric UID (109, 43)

Runtime detection in `tor_manager.py`:

```python
TOR_USER = "debian-tor" if subprocess.run(["getent", "passwd", "debian-tor"], capture_output=True).returncode == 0 else "tor"
TOR_UID = subprocess.run(["id", "-u", TOR_USER], capture_output=True, text=True).stdout.strip()
```

---

## Enable Flow

```
enable()
  1. Check `which tor` — error if not installed
  2. Detect TOR_USER / TOR_UID
  3. Write torrc additions (idempotent — skip if already present)
  4. sudo systemctl restart tor
  5. Poll stem ControlPort 9051: GETINFO status/circuit-established
     - Poll every 1s, timeout 30s
     - Timeout → rollback, return error
  6. Verify via httpx (SOCKS5 9050) → check.torproject.org/api/ip
     - Assert response["IsTor"] == True
     - Failure → rollback, return error
  7. Apply iptables PLIA_TOR chain
  8. Update config: tor_enabled = True
  9. Start monitor_loop() background asyncio task
 10. Return "Tor enabled. Exit node: {country} {ip}"
```

---

## Monitor Loop

Background asyncio task, runs every 10 seconds:

```
monitor_loop()
  - stem GETINFO status/circuit-established
  - if circuits lost:
      - activate kill switch (iptables DROP)
      - set module-level _kill_switch_active = True
      - emit tor_status event → WebSocket broadcast
      - notify-send "Plia: Tor dropped — all traffic blocked. Reason: {error}"
      - update config: tor_enabled = False
      - stop loop
```

No auto-recovery — user must explicitly re-enable. Kill switch stays active until `disable_tor()` is called.

`_kill_switch_active` is runtime state in `tor_manager.py` (not persisted to config). `disable_tor()` checks it and flushes kill switch rules before restoring OUTPUT ACCEPT policy.

---

## Disable Flow

```
disable()
  1. Cancel monitor_loop task
  2. Flush iptables PLIA_TOR chain (transparent proxy rules)
  3. Flush kill switch rules and restore OUTPUT ACCEPT policy
  4. sudo systemctl stop tor
  5. Update config: tor_enabled = False
  6. Return "Tor disabled. Clearnet restored."
```

Disable with active kill switch: kill switch flushed first, then proxy rules, then policy ACCEPT.

---

## Startup Persistence

In `core/main.py` lifespan: if `config.tor_enabled`, call `tor_manager.enable()`. Failure on startup logs error and sets `tor_enabled = False` (does not block app startup).

---

## Sudo Requirements

`enable()` writes `/etc/sudoers.d/plia-tor` on first run:

```
plia ALL=(root) NOPASSWD: /usr/sbin/iptables, /usr/bin/systemctl start tor, /usr/bin/systemctl stop tor, /usr/bin/systemctl restart tor
```

If sudoers write fails, error message instructs user to add manually.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `tor` not installed | Return "tor not installed. Run: sudo apt install tor" — no iptables touched |
| `stem` not installed | Fall back to `pgrep tor` process poll — logs warning |
| Circuit timeout (>30s) | Rollback rules, stop tor, return error with timeout detail |
| `check.torproject.org` returns IsTor=False | Rollback, return "Traffic not routing through Tor — iptables may be misconfigured" |
| iptables command fails | Rollback all rules applied so far, return full stderr |
| Kill switch fires | `notify-send` with reason + WebSocket `tor_status` event |
| Disable with active kill switch | Flush kill switch first, then proxy rules, restore ACCEPT |

---

## Dashboard UI

New "VPN / Tor" section in Settings > Network:

**Disabled state:**
```
[ Tor Network ]  ●──○  [Enable]
Status: Disabled
```

**Enabled state:**
```
[ Tor Network ]  ○──●  [Disable]
Status: Connected · Exit node: DE (Frankfurt) · 185.220.x.x
```

**Kill switch active:**
```
[ Tor Network ]  ○──●  [Disable]
Status: ⚠ Kill switch active — all traffic blocked
```

Status updates via WebSocket event type `tor_status`. `GET /api/tor/status` returns current state for page load.

---

## Tool Functions (`modules/tor_tools.py`)

```python
@tool("Enable system-wide Tor routing for all network traffic.")
def enable_tor() -> str: ...

@tool("Disable Tor routing and restore direct clearnet access.")
def disable_tor() -> str: ...

@tool("Get current Tor status: enabled/disabled, exit node IP and country.")
def tor_status() -> str: ...
```

---

## Supervisor Keyword Routes

Added to `"respond"` list in `_KEYWORD_ROUTES`:

```python
"enable tor", "turn on tor", "start tor", "enable vpn", "turn on vpn",
"route through tor", "use tor", "anonymize",
"disable tor", "turn off tor", "stop tor", "disable vpn", "turn off vpn",
"tor status", "vpn status", "am i anonymous", "check tor", "my ip",
```

---

## API Endpoints

```
GET  /api/tor/status   → {enabled, exit_ip, exit_country, kill_switch_active}
POST /api/tor/enable   → {success, message}
POST /api/tor/disable  → {success, message}
```

---

## Dependencies

- `tor` system package (not a Python dep — user installs via apt/pacman)
- `stem` Python package — optional extra: `pip install -e ".[tor]"` in `pyproject.toml`
- `httpx` — already a dependency (for verification step)

---

## Files Changed

| File | Change |
|------|--------|
| `modules/tor_tools.py` | New — 3 @tool functions |
| `core/tor_manager.py` | New — TorManager, enable, disable, monitor_loop |
| `core/config.py` | Add `tor_enabled: bool = False` |
| `core/main.py` | Call `tor_manager.enable()` in lifespan if `config.tor_enabled` |
| `core/supervisor.py` | Add tor keywords to `"respond"` list |
| `dashboard/server.py` | Add GET/POST /api/tor/* endpoints |
| `dashboard/static/index.html` | Add VPN/Tor toggle in Settings > Network |
| `pyproject.toml` | Add `[tor]` optional extra for `stem` |
| `tests/test_tor_tools.py` | New — @tool function tests |
| `tests/test_tor_manager.py` | New — enable/disable/monitor/rollback tests |
