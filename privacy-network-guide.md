# Privacy & Network — User Guide

How to use every tool in the **Network** (Privacy & Network) category of the
Plia-OS Tools panel. This guide tells you *what each tool does, how to ask for it,
what parameters it needs, and what you have to do before it will run* — in plain
language.

You can use these tools two ways:

1. **Just ask** in chat or voice (e.g. *"Connect to my wifi"*, *"What's my MAC
   address?"*, *"Check my wifi password strength"*).
2. **Click a tool** in **🔧 Tools → Network** in the dashboard, fill in the
   fields, and run it.

The category contains five groups: **MAC**, **WiFi**, **IP**, **Network Check**,
plus **Tor**, **Diagnostics**, and the connect/saved-network helpers. Every field
you can fill in is explained in [§8 — Parameters reference](#8-parameters-reference).

---

## 1. MAC address

The hardware address of a network adapter. Changing it can help with privacy on
public networks.

| Tool | What it does | How to ask |
|------|--------------|------------|
| `list_macs()` | Show every interface with its MAC and type. | "List my MAC addresses" |
| `show_mac(interface)` | Show one interface's current MAC. | "Show my MAC" |
| `randomize_mac(interface)` | Set a random MAC; the original is saved. | "Randomize my MAC" |
| `set_mac(interface, mac_address)` | Set a specific MAC. | "Set wlan0 MAC to 02:1a:3b:4c:5d:6e" |
| `restore_mac(interface)` | Put back the original MAC saved earlier. | "Restore my MAC" |

**Needed to change (not to view):** the **Network Interface Control** grant
(`/etc/sudoers.d/plia-mac`) **and** the tool set to `admin` in
**Settings → Permissions**. `list_macs`/`show_mac` need nothing.

---

## 2. WiFi

Two halves: everyday connection management (nmcli-based, no special grant), and
wireless security testing (monitor mode, needs the Wireless Tools grant).

### 2a. Everyday WiFi

| Tool | What it does | How to ask |
|------|--------------|------------|
| `list_wifi_interfaces()` | List WiFi adapters and their state. | "List wifi interfaces" |
| `scan_wifi(interface)` | Nearby networks: name, BSSID, signal, security, channel. | "Scan for wifi networks" |
| `wifi_status()` | Your current connection (SSID, signal, IP). | "What wifi am I on?" |
| `list_saved_wifi()` | Networks you've joined before (no password needed again). | "What wifi networks have I saved?" |
| `connect_wifi(ssid, interface, password)` | Connect to a network, reusing a saved profile. | "Connect to my wifi" |
| `enable_wifi_dongle(interface)` | Enable a USB WiFi dongle and connect it. | "Enable the wifi dongle" |
| `disable_wifi_dongle(interface)` | Disconnect a USB dongle and keep it down. | "Disable the wifi dongle" |
| `internal_wifi_status()` | Whether the internal Intel WiFi driver is blacklisted/loaded. | "Internal wifi status" |
| `disable_internal_wifi()` | Fully disable the internal Intel card (reboot required). | "Disable internal wifi" |
| `enable_internal_wifi()` | Undo that and load the driver again. | "Enable internal wifi" |
| `reactivate_internal_network()` | Full recovery when the internal card was disabled or disappeared: clear the blacklist, unblock rfkill, reload the driver and bring the interface back. | "Reactivate the internal network" |

`connect_wifi` details:

- Leave `ssid` empty to auto-connect to the **strongest saved network in range**.
- Pass `password` only for a brand-new network; saved networks don't need it.
- If a network needs a password you don't have, it offers to recover the key via
  the wireless security tools (§2b) — only do this on your own network.

The internal-wifi blacklist/recovery tools need the **Internal WiFi Blacklist**
grant (`/etc/sudoers.d/plia-iwlwifi`).

### 2b. Wireless security testing

> **Use only on networks you own or have explicit permission to test.
> Unauthorized use is illegal.** These drive the aircrack-ng suite and need the
> **Wireless Tools** grant (`/etc/sudoers.d/plia-wireless`) plus the tool set to
> `admin`, and a WiFi adapter that supports monitor mode.

| Tool | What it does | Prereq |
|------|--------------|--------|
| `install_wireless_tools()` | Install aircrack-ng, reaver, wash, crunch. | — |
| `start_monitor_mode(interface)` | Put the adapter in monitor mode for capture. | grant + admin |
| `stop_monitor_mode(interface)` | Return to managed mode and restart NetworkManager. | grant + admin |
| `kill_interfering_processes()` | Stop NetworkManager/wpa_supplicant so capture works (WiFi drops until stopped). | grant + admin |
| `monitor_scan_networks(interface, scan_seconds)` | Detailed scan (BSSID, channel, signal, encryption). | monitor mode |
| `scan_wps_networks(interface, scan_seconds)` | Find WPS-enabled APs. | monitor mode |
| `capture_handshake(interface, bssid, channel, output_dir, passive)` | Deauth a client (unicast + broadcast) to force reconnect and capture the WPA handshake. Auto-starts/restores monitor mode; refuses an idle BSSID. `passive=true` skips deauth for 802.11w/PMF clients — toggle the client's WiFi during the 90 s window. | managed or monitor adapter |
| `create_wordlist(min_len, max_len, charset, output_file)` | Generate a wordlist with crunch (max 15; huge lists are refused). | — |
| `crack_handshake_rockyou(capture_file, bssid)` | Crack a capture with rockyou.txt. | — |
| `crack_handshake_wordlist(capture_file, bssid, wordlist_file)` | Crack with a custom wordlist. | — |
| `crack_handshake_auto(capture_file, bssid)` | Crack with generated digits (8–10 chars). | — |
| `attack_wps(interface, bssid, channel, timeout_seconds, pixie_dust)` | WPS attack: Pixie Dust, then automatic PIN stages of 300/900/1800 s, then an extension prompt with a seconds input. Auto-starts and restores monitor mode. | managed or monitor adapter |
| `download_rockyou()` | Fetch the rockyou.txt wordlist (~51 MB) if missing. | — |
| `gain_wifi_access(ssid, interface)` | Full auto flow: WPS → handshake+crack → connect. | grant + admin |
| `reveal_hidden_ssid(interface)` | Reveal non-broadcasting SSIDs by deauthing clients. | grant + admin |

Typical order when testing your own network: `install_wireless_tools` →
`start_monitor_mode` → `monitor_scan_networks` → (pick BSSID/channel) → act →
`stop_monitor_mode` to clean up.

---

## 3. IP address (LAN)

| Tool | What it does | How to ask |
|------|--------------|------------|
| `show_ip(interface)` | Current local IPv4 address/subnet. | "What's my local IP?" |
| `randomize_local_ip(interface)` | Pick a random unused address in your subnet (original saved). | "Randomize my local IP" |
| `set_local_ip(interface, ip_cidr)` | Set a specific address. | "Set my IP to 192.168.1.50/24" |
| `restore_ip(interface)` | Restore the original address saved earlier. | "Restore my IP" |

Changes are **transient** (revert on network refresh/reboot and briefly drop
connections). They need the **Network Interface Control** grant
(`/etc/sudoers.d/plia-mac`).

---

## 4. Network Check (netpass)

Defensive, **read-only** audits of a network you own. Run the standalone netpass
program; nothing is changed.

| Tool | What it does | How to ask |
|------|--------------|------------|
| `check_password(password)` | Rate a password's strength and explain weaknesses. | "Check this password: hunter2" |
| `check_wifi_password()` | Check the saved key of the Wi-Fi you're on. | "Check my wifi password" |
| `scan_local_network(target, deep)` | Scan the LAN for devices and risky exposed services. | "Scan my network" / "Scan 192.168.1.0/24" |
| `external_exposure_check()` | What your network exposes to the public internet. | "What does my network expose?" |

`scan_local_network` with no `target` auto-detects your /24; `deep=True` adds nmap
CVE scripts (much slower). A full scan needs root: Plia opens its
administrator-password dialog when sudo needs one. On a headless host it points
you to **Monitor/Developer → Network Check**, where you enter the password once
and it's never stored.

---

## 5. Tor routing

| Tool | What it does | How to ask |
|------|--------------|------------|
| `enable_tor()` | Route all system traffic through Tor. | "Enable Tor" |
| `disable_tor()` | Restore direct clearnet access. | "Disable Tor" |
| `tor_status()` | Whether Tor is on, exit-node IP, kill-switch state. | "Tor status" |

The kill switch blocks traffic if the Tor circuit drops; `tor_status` tells you to
reconnect.

---

## 6. Network diagnostics

| Tool | What it does | How to ask |
|------|--------------|------------|
| `public_ip()` | Your public internet IP, ISP, and rough location. | "What's my public IP?" |
| `ping_host(host, count)` | Ping a host (latency + packet loss). | "Ping 1.1.1.1" |
| `dns_lookup(hostname)` | Resolve a domain to IPs. | "Resolve example.com" |
| `network_speedtest()` | Approximate download/upload speed. | "Run a speed test" |

`public_ip` and `network_speedtest` contact external services that will see your
IP.

---

## 7. Tools that need no parameters

Just run these — they take no arguments:

`list_macs` · `list_wifi_interfaces` · `wifi_status` · `list_saved_wifi` ·
`internal_wifi_status` · `disable_internal_wifi` · `enable_internal_wifi` ·
`reactivate_internal_network` ·
`install_wireless_tools` · `kill_interfering_processes` · `download_rockyou` ·
`check_wifi_password` · `external_exposure_check` · `enable_tor` · `disable_tor` ·
`tor_status` · `public_ip` · `network_speedtest`

---

## 8. Parameters reference

What to type into each field. Fields marked **(required)** must be filled in;
everything else has a sensible default when left blank.

### `interface`
The OS name of the network adapter to act on — e.g. `wlan0`, `eth0`, `wlp3s0`,
or a monitor interface like `wlan0mon`. **Leave blank to auto-detect** the active
adapter; set it only when you have more than one. In the dashboard this field is a
dropdown showing real adapters (container/VM interfaces like `veth*`, `docker*`,
`br-*`, `virbr*` are hidden).

- Used by: all MAC, WiFi, IP, and wireless tools that take it.
- Example: `wlan0`

### `mac_address`
A specific MAC (hardware) address to assign, in the form `XX:XX:XX:XX:XX:XX` —
six hex byte-pairs. Used by **Set Mac** to force one specific address instead of a
random one.

- Used by: `set_mac`.
- Format: `XX:XX:XX:XX:XX:XX`
- Example: `02:1a:3b:4c:5d:6e`

### `ssid`
The Wi-Fi network name to target. For `connect_wifi`, leave it blank to
auto-connect to the strongest saved network in range. Partial names are matched
("home" resolves to "Home Network").

- Used by: `connect_wifi`, `gain_wifi_access`.
- Example: `Home Network`

### `password` (connect_wifi)
The Wi-Fi password. **Only needed for a brand-new network** — saved networks
reuse their stored credentials, so this stays empty for anything you've joined
before.

- Used by: `connect_wifi`.

### `ip_cidr`
A specific local IPv4 address to assign, in CIDR form `A.B.C.D/prefix`. The
`/prefix` is the subnet size (`/24` = typical home LAN). Pick an **unused** address
inside your current subnet.

- Used by: `set_local_ip`.
- Format: `A.B.C.D/prefix`
- Example: `192.168.1.50/24`

### `bssid`
The target access point's **BSSID** — the router's own MAC address, format
`XX:XX:XX:XX:XX:XX`. It pinpoints the exact network to act on. **Copy it from a
`scan_wifi`, `monitor_scan_networks`, or `scan_wps_networks` result.**

- Used by: `capture_handshake`, `attack_wps`, `crack_handshake_rockyou`,
  `crack_handshake_wordlist`, `crack_handshake_auto`.
- Format: `XX:XX:XX:XX:XX:XX`
- Example: `A0:1B:2C:3D:4E:5F`

### `channel`
The Wi-Fi channel the target network broadcasts on — a number like `1`, `6`, `11`
(2.4 GHz) or `36`/`149` (5 GHz). Tunes the adapter to that access point. **Read it
from a scan result.**

- Used by: `capture_handshake`, `attack_wps`.
- Example: `6`

### `scan_seconds`
How long, in seconds, to capture traffic before the monitor-mode scanner
(airodump-ng) stops and returns what it found. Longer scans catch more networks
and clients (especially weak or busy ones) but take longer.

- Used by: `monitor_scan_networks` (default 15, capped at 30), `scan_wps_networks`
  (default 20, capped at 60).
- Example: `20`

### `output_dir`
Directory where the handshake capture file is written. Must be a writable folder.

- Used by: `capture_handshake`.
- Default: `/tmp`
- Example: `/tmp`

### `capture_file`
Path to a captured WPA handshake file — the `.cap` produced by **Capture
Handshake** — that you want to crack. Use **Browse** to pick it.

- Used by: `crack_handshake_rockyou`, `crack_handshake_wordlist`,
  `crack_handshake_auto`.
- Example: `/tmp/plia_A01B2C3D4E5F-01.cap`

### `wordlist_file`
Path to a password wordlist to test against the handshake — e.g. `rockyou.txt` or
a list made with **Create Wordlist**. Use **Browse** to pick it.

- Used by: `crack_handshake_wordlist`.
- Example: `/usr/share/wordlists/rockyou.txt`

### `min_len` / `max_len`
The minimum and maximum length (in characters) of the password candidates
**Create Wordlist** generates. A higher minimum means fewer, longer guesses;
raising the maximum grows the list size exponentially, so keep it close to the
minimum unless you specifically need it.

- Used by: `create_wordlist`.
- Default: both `8` (`max_len` ≤ 12, `min_len` ≥ 1).

### `charset`
The set of characters the wordlist generator draws from. More characters means an
exponentially larger list.

- Used by: `create_wordlist`.
- Default: `abcdefghijklmnopqrstuvwxyz0123456789` (lowercase letters + digits).
- Example: `abcdefghijklmnopqrstuvwxyz0123456789`

### `output_file` (wordlist)
Full path where the generated wordlist is saved. An existing file at that path is
overwritten.

- Used by: `create_wordlist`.
- Default: `/tmp/plia_wordlist.txt`

### `timeout_seconds` / `pixie_dust` (attack_wps)
`timeout_seconds=0` (default) runs the automatic PIN stages: 300 s, 900 s, then
1800 s. After those it asks whether to extend; the dashboard shows an input for
extra seconds (max 3600). A positive value runs one extension budget directly.
`pixie_dust` (default `true`) tries the fast Pixie-Dust attack first.

- Used by: `attack_wps`.

### `target` / `deep` (scan_local_network)
`target` is the host, hostname, or CIDR range to scan — leave blank to auto-detect
your `/24` subnet. `deep` (default `false`) also runs nmap's CVE scripts, which is
much slower.

- Used by: `scan_local_network`.
- Examples: blank, `192.168.1.1`, `192.168.1.0/24`

### `password` (check_password)
The password string to evaluate for strength. It is checked **locally** and never
sent anywhere.

- Used by: `check_password`.
- Example: `hunter2`

### `host` / `count` (ping_host)
`host` is the hostname or IP to ping. `count` is how many packets to send (1–10;
more gives a steadier average, default 4).

- Used by: `ping_host`.
- Examples: `1.1.1.1`, `example.com`

### `hostname` (dns_lookup)
A domain name to resolve to its IP address(es).

- Used by: `dns_lookup`.
- Example: `example.com`

---

## 9. Permissions and grants

Only two things are needed for the privileged tools, and they're **independent**:

1. The tool set to `admin` in **Settings → Permissions** (saved to
   `tool_permissions`).
2. A sudoers file created by the **"How to Grant"** command under each group —
   run it in a real terminal, as it needs `sudo`:

| Group | Grant file | Unlocks |
|-------|-----------|---------|
| Network Interface Control | `/etc/sudoers.d/plia-mac` | MAC change + IP change tools |
| Wireless Tools | `/etc/sudoers.d/plia-wireless` | monitor mode, handshake, WPS, cracking |
| Internal WiFi Blacklist | `/etc/sudoers.d/plia-iwlwifi` | internal-wifi disable/enable/reactivate |

Revoke any grant with `sudo rm /etc/sudoers.d/<file>`. View status under
**Settings → Permissions** (shows whether each grant is installed).

---

## 10. Quick chat cheat sheet

| Want | Say |
|------|-----|
| See your network cards | "List my MAC addresses" |
| Hide your adapter ID | "Randomize my MAC" |
| See nearby networks | "Scan for wifi" |
| See current network | "What wifi am I on?" |
| Join a network | "Connect to the Home network" |
| See saved networks | "What wifi have I saved?" |
| Check local address | "What's my local IP?" |
| Rate a password | "Check this password: …" |
| Audit your LAN | "Scan my network" |
| Go anonymous | "Enable Tor" |
| Test connectivity | "Ping 1.1.1.1" / "Resolve example.com" / "Run a speed test" |

For the wireless security-testing tools (monitor mode, handshake, WPS, cracking),
always confirm you own the network or have written permission first — see the
[authorized test plan template](wifi-pentest-plan-template.md) before doing any of
it.
