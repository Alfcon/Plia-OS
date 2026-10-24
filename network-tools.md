# Plia-OS — Network Tools Guide

This document describes every network-related tool currently registered in Plia-OS,
how to invoke them, and what permissions each one needs. It is generated from the
tool definitions in `modules/` and the permission groups in `dashboard/server.py`.

Network tools live in five modules:

| Module | Purpose |
|--------|---------|
| `modules/network_tools.py` | Everyday network management — MAC, WiFi, IP |
| `modules/network_check_tools.py` | Defensive network auditing (netpass) |
| `modules/tor_tools.py` | Tor anonymity routing |
| `modules/web_tools.py` | Web search and page scraping |
| `modules/wireless_tools.py` | Wireless security testing (aircrack-ng suite) |

---

## 1. How tools are invoked

Tools are LLM function-calling tools registered via `@tool(...)` in each module.
They can be run three ways:

1. **Chat / voice** — ask in natural language, e.g. *"Connect to my wifi"*,
   *"Scan for wifi networks"*, *"What's my MAC address?"*. The supervisor routes
   the request and the LLM calls the tool with generated arguments.
2. **Tools panel** — open **🔧 Tools → Network** in the dashboard. All privacy and
   network tools are listed with argument forms and, where relevant, interface
   dropdowns that only offer valid adapters.
3. **HTTP API** — a few operations are exposed as dashboard endpoints (see
   [§8](#8-dashboard-http-endpoints)).

Most tools take an optional `interface` argument. It is the OS name of a network
adapter (e.g. `wlan0`, `wlp3s0`, `eth0`, or a monitor interface like `wlan0mon`).
Leave it empty to auto-detect the active adapter. Container/VM interfaces
(`veth*`, `docker*`, `br-*`, `virbr*`, `dummy`) are filtered out of auto-detection.

---

## 2. Permission model

Two independent gates control the privileged tools.

### 2.1 Tool permission (`admin` vs `user`)

`core/config.py` has `tool_permissions: dict` mapping a tool name to `"admin"` or
`"user"`. Set this in **Settings → Permissions** in the dashboard; each system
grant group shows how many of its tools are still `user` and has a one-click
**Set tools to Admin** button. A tool must be `admin` for the privileged paths
to run; otherwise it fails with "Permission denied."

### 2.2 OS-level sudoers grants

Privileged tools also require a `NOPASSWD` sudoers file in `/etc/sudoers.d/`.
These are defined as `_OS_PERMISSION_GROUPS` in `dashboard/server.py` and created
by the **"How to Grant"** command shown under each group. They need `sudo`, so
they must be run in a real terminal (not from inside the assistant).

| Group | sudoers file | Tools it unlocks |
|-------|--------------|------------------|
| Network Interface Control | `/etc/sudoers.d/plia-mac` | `randomize_mac`, `set_mac`, `restore_mac`, `randomize_local_ip`, `set_local_ip`, `restore_ip` |
| Wireless Tools | `/etc/sudoers.d/plia-wireless` | `start_monitor_mode`, `stop_monitor_mode`, `kill_interfering_processes`, `capture_handshake`, `attack_wps`, `scan_wps_networks` |
| Internal WiFi Blacklist | `/etc/sudoers.d/plia-iwlwifi` | `disable_internal_wifi`, `enable_internal_wifi`, `reactivate_internal_network` |

A grant is considered present when its sudoers file exists (checked without sudo).
Revoke any grant with `sudo rm /etc/sudoers.d/<file>`.

---

## 3. MAC address tools (`network_tools.py`)

Require the **Network Interface Control** grant (`/etc/sudoers.d/plia-mac`) plus
the tool set to `admin` for any *change*; `list_macs`/`show_mac` are read-only.

| Tool | Purpose |
|------|---------|
| `list_macs()` | List all physical interfaces with MAC address and type (WiFi/Ethernet/Other). |
| `show_mac(interface="")` | Current MAC of one interface (auto-detect if empty). |
| `randomize_mac(interface="")` | Assign a random, locally-administered MAC; saves the original for restore. |
| `set_mac(interface="", mac_address)` | Set a specific MAC, format `XX:XX:XX:XX:XX:XX`. |
| `restore_mac(interface="")` | Restore the original MAC previously saved by Plia-OS. |

The original MAC is remembered in the memory store under `original_mac_<iface>` on
first change, so `restore_mac` only works after a prior change. `randomize_mac`
generates a unicast, locally-administered address (first octet `x2`-style).

Example chat: *"Randomize my MAC address"*, *"Set wlan0's MAC to 02:1a:3b:4c:5d:6e"*.

---

## 4. WiFi tools (`network_tools.py`)

These use **nmcli** (NetworkManager). If nmcli is absent, every tool degrades to a
clear message instead of raising. Scanning uses a shared 15-second budget because
`nmcli dev wifi list` triggers a rescan that is slow on a cold cache.

| Tool | Purpose |
|------|---------|
| `list_wifi_interfaces()` | WiFi adapters with state and active connection. |
| `scan_wifi(interface="")` | Nearby networks: SSID, BSSID, signal %, security, channel. Hidden SSIDs appear as `<hidden>`. |
| `wifi_status()` | Current connection: interface, SSID, signal, security, channel, IP. |
| `list_saved_wifi()` | Networks saved on this machine (reconnectable without a password). |
| `connect_wifi(ssid="", interface="", password="")` | Connect to a network; reuses saved credentials. |

`connect_wifi` behaviour:

- **SSID given** — resolves the name (exact saved profile → exact SSID → saved
  containment → strongest-signal containment) and connects via
  `nmcli device wifi connect`.
- **SSID empty** — connects to the strongest saved network in range; if exactly
  one saved profile exists it is brought up directly.
- **`password`** — only needed for a brand-new network. If a connection fails
  because no saved key exists, it offers to recover the key via the wireless
  security tools (see [§7](#7-wireless-security-tools-wireless_toolspy)).

### USB WiFi dongle management

| Tool | Purpose |
|------|---------|
| `enable_wifi_dongle(interface="")` | Mark the dongle managed, enable autoconnect, and connect it. |
| `disable_wifi_dongle(interface="")` | Disconnect the dongle and disable autoconnect. |

These auto-detect a USB WiFi adapter (by `/sys/class/net/<iface>` symlink
containing `/usb`, or a `wlx<mac>` name). Pass `interface` explicitly if more than
one is present.

### Internal WiFi driver blacklist (full disable)

For freeze-testing on a USB dongle. Requires the **Internal WiFi Blacklist** grant.

| Tool | Purpose |
|------|---------|
| `internal_wifi_status()` | Whether the iwlwifi/iwlmvm blacklist file exists and whether the driver is loaded. |
| `disable_internal_wifi()` | Write `/etc/modprobe.d/disable-internal-wifi.conf`, rebuild initramfs. A **reboot is required**. |
| `enable_internal_wifi()` | Remove the blacklist, rebuild initramfs, and modprobe iwlwifi. |
| `reactivate_internal_network()` | Full recovery when the internal card was disabled or disappeared: remove the blacklist, rebuild initramfs, `rfkill unblock wifi`, reload `iwlwifi`/`iwlmvm`, bring the interface up and set it managed by NetworkManager. Safe to run when the card is already active (it only reports). |

---

## 5. Local IP tools (`network_tools.py`)

Require the **Network Interface Control** grant. Changes are transient (they revert
on network refresh/reboot and briefly drop connections).

| Tool | Purpose |
|------|---------|
| `show_ip(interface="")` | Current IPv4 address/subnet of an interface. |
| `randomize_local_ip(interface="")` | Pick a random unused host in the current subnet; saves the original. |
| `set_local_ip(interface="", ip_cidr)` | Set a specific IPv4, format `A.B.C.D/prefix` (e.g. `192.168.1.50/24`). |
| `restore_ip(interface="")` | Restore the original address saved before a change. |

The original is remembered as `original_ip_<iface>` in the memory store.

---

## 6. Network auditing — netpass (`network_check_tools.py`)

Defensive, **read-only and advisory** checks that shell out to the standalone
`netpass` program (`/home/alfcon/Projects/Netpass/netpass.py` via its own
virtualenv, which bundles python-nmap). Nothing is changed on the network.

The local-network scan runs under `sudo`: when a password is needed (no
passwordless rule or cached credentials), Plia opens its administrator-password
dialog. On a headless host without a dialog the tool fails fast and points at the
dashboard's **Monitor/Developer → Network Check** panel instead. The dashboard
endpoint takes a sudo password once (used with `sudo -S`, never stored).

| Tool | Underlying command | Purpose |
|------|--------------------|---------|
| `check_password(password)` | `netpass --check-password` | Rate a password string's strength; report weaknesses and fixes. Evaluated locally. |
| `check_wifi_password()` | nmcli saved profile, then `netpass --check-wifi` | Show the saved key of the Wi-Fi this machine is on (NetworkManager/nmcli fallback when netpass is unavailable). |
| `scan_local_network(target="", deep=False)` | `netpass [target] --report [--deep]` | Scan the LAN for devices and flag risky exposed services with fixes. Blank target auto-detects the /24; `deep` adds nmap CVE scripts (much slower). |
| `external_exposure_check()` | `netpass --external` | Show what your network exposes publicly via Shodan's free InternetDB (public IP, open ports, known CVEs). Contacts external services. |

Use only on networks you own or are authorized to scan.

---

## 7. Wireless security tools (`wireless_tools.py`)

> **Use only on networks you own or have explicit permission to test. Unauthorized
> use is illegal.** These tools drive the aircrack-ng suite (airmon-ng, airodump-ng,
> aireplay-ng, aircrack-ng), reaver, wash, and crunch.

These tools require the **Wireless Tools** grant (`/etc/sudoers.d/plia-wireless`)
plus the relevant tool set to `admin`, and a WiFi adapter capable of monitor mode.

### Setup and monitor mode

| Tool | Purpose |
|------|---------|
| `install_wireless_tools()` | `apt-get install` aircrack-ng, reaver, and crunch; verify binaries; fetch rockyou.txt if missing. |
| `start_monitor_mode(interface="")` | Put the adapter in monitor mode via `airmon-ng start`. Does **not** kill NetworkManager (that is a separate, explicit action). |
| `kill_interfering_processes()` | Run `airmon-ng check kill` — stops NetworkManager/wpa_supplicant/avahi. WiFi stays down until monitor mode is stopped. |
| `stop_monitor_mode(interface="")` | `airmon-ng stop` and restart NetworkManager to return to managed mode. |
| `download_rockyou()` | Fetch rockyou.txt (~51 MB) when it is not installed. |

### Scanning

| Tool | Purpose |
|------|---------|
| `monitor_scan_networks(interface="", scan_seconds=15)` | Detailed airodump-ng scan: BSSID, channel, signal (dBm), encryption. Cap 30 s. |
| `scan_wps_networks(interface, scan_seconds=20)` | `wash` scan for WPS-enabled APs. Requires a monitor interface. |

### Credential-recovery tools

These follow the classic WPA/WPS assessment flow: capture the 4-way handshake by
deauthenticating a client, then crack it offline; or attack WPS.

| Tool | Purpose |
|------|---------|
| `capture_handshake(interface, bssid, channel, output_dir="/tmp", passive=False)` | Starts monitor mode automatically if `interface` is managed, checks the target BSSID has an associated client, then sends unicast+broadcast deauth to force a reconnect and verifies aircrack-ng sees the handshake. A final passive window catches late reconnects. `passive=true` skips deauth entirely for 802.11w/PMF clients — reconnect the client's WiFi during the 90 s window. Restores managed mode afterwards. |
| `create_wordlist(min_len=8, max_len=8, charset=…, output_file=…)` | Generate a wordlist with crunch. Supports lengths up to 15 and a mixed letters+digits default charset, but refuses estimates over ~50M candidates (~0.6 GB) to avoid filling the disk. |
| `crack_handshake_rockyou(capture_file, bssid)` | Crack a capture with rockyou.txt. Can run up to 60 min on a laptop CPU. |
| `crack_handshake_wordlist(capture_file, bssid, wordlist_file)` | Crack a capture with a custom wordlist. |
| `crack_handshake_auto(capture_file, bssid)` | Crack a capture with an on-the-fly digits-only wordlist (8–10 chars). |
| `attack_wps(interface, bssid, channel, timeout_seconds=0, pixie_dust=True)` | WPS attack via reaver — Pixie Dust first, then automatic PIN stages of 300 s, 900 s and 1800 s. After those it asks whether to extend; the dashboard shows an input for extra seconds (max 3600). `interface` may be managed: monitor mode is started automatically and restored. |

### Higher-level helpers

| Tool | Purpose |
|------|---------|
| `gain_wifi_access(ssid, interface="")` | Orchestrate the full flow automatically: WPS first, then handshake capture + crack (rockyou, then digits auto-list), then connect. |
| `reveal_hidden_ssid(interface="")` | Put the adapter in monitor mode, deauth clients on every non-broadcasting AP so they re-announce the SSID, and report the revealed names. |

`connect_wifi` falls back to `gain_wifi_access` automatically when a network needs
a password and none is saved.

### Handshake-verification note

A capture file is always produced even when no handshake is present, so the code
asks **aircrack-ng** to count handshakes (scoped to the target BSSID) before
declaring a capture usable. WPA3-only (SAE) networks cannot be cracked from a
4-way handshake.

---

## 8. Tor routing (`tor_tools.py` + `core/tor_manager.py`)

Route all system traffic through Tor via iptables NAT rules.

| Tool | Purpose |
|------|---------|
| `enable_tor()` | Enable system-wide Tor routing. |
| `disable_tor()` | Disable Tor and restore direct clearnet access. |
| `tor_status()` | Whether Tor is enabled, the exit-node IP, and kill-switch state. |

The kill switch blocks all traffic when the Tor circuit drops; `tor_status`
reports `kill_switch_active` and says to run `enable tor` to reconnect.

---

## 9. Web tools (`web_tools.py`)

| Tool | Purpose |
|------|---------|
| `search_web(query)` | Search the web (DuckDuckGo by default, or Google when a key/CX are configured). Returns title/snippet/URL. |
| `scrape_url(url)` | Fetch a page and return its stripped text (first ~2000 chars). |

---

## 10. Dashboard HTTP endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/network/wifi` | Current WiFi status + nearby networks (same helpers as `wifi_status`/`scan_wifi`). |
| `GET /api/network/mac` | List interfaces and MACs (`list_macs`). |
| `POST /api/network/mac/randomize` | Randomize MAC (`body: {"interface": ""}`). |
| `POST /api/network/mac/restore` | Restore MAC. |
| `GET /api/network/interfaces` | Interfaces and addresses from `ip addr`. |
| `POST /api/netcheck/scan` | Run the elevated netpass scan with a sudo password (used once, never stored). |
| `GET /api/permissions` | Permission groups, their grant/revoke commands, and whether each sudoers grant is installed. |

---

## 11. Quick reference

**Everyday (no grant needed)**
`list_macs` · `show_mac` · `list_wifi_interfaces` · `scan_wifi` · `wifi_status` ·
`list_saved_wifi` · `connect_wifi` · `show_ip` · `search_web` · `scrape_url` ·
`tor_status` · `enable_tor` · `disable_tor`

**Network Interface Control grant (`/etc/sudoers.d/plia-mac`)**
`randomize_mac` · `set_mac` · `restore_mac` · `randomize_local_ip` ·
`set_local_ip` · `restore_ip`

**Wireless Tools grant (`/etc/sudoers.d/plia-wireless`)**
`start_monitor_mode` · `stop_monitor_mode` · `kill_interfering_processes` ·
`capture_handshake` · `attack_wps` · `scan_wps_networks` (plus the other
monitor/scan/crack tools, which share the same admin gate)

**Internal WiFi Blacklist grant (`/etc/sudoers.d/plia-iwlwifi`)**
`disable_internal_wifi` · `enable_internal_wifi` · `reactivate_internal_network`

**netpass auditing (no Plia grant; scan needs root via the Plia password dialog or the dashboard)**
`check_password` · `check_wifi_password` · `scan_local_network` ·
`external_exposure_check`
