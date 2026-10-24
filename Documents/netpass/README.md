# NetPass

A Python network scanner and home-network security tool, built on
[`python-nmap`](https://pypi.org/project/python-nmap/). Run it and it discovers
every device on your network and prints them as a table — hostname, MAC address,
vendor, OS guess, and open ports.

It also helps you secure what it finds:

- **Security report** (`-r`) — flags risky exposures per device with a fix and a severity.
- **External exposure check** (`--external`) — sees what your network exposes to the internet.
- **Deep CVE detection** (`--deep`) — maps services to known CVEs via nmap's vuln scripts.
- **Vendor lookup** — a self-updating IEEE database, so even brand-new devices are identified.
- **Device labels** — give devices names that stick by MAC address.
- **Wi‑Fi password check** — rate your Wi‑Fi password's strength locally.

> ⚠️ **Use responsibly.** Only scan networks you own or have permission to test.

---

## Install

NetPass needs the **nmap** program and the **python-nmap** library.

**1. Install nmap** (the library is just a wrapper around it):

```bash
sudo apt install nmap      # Debian / Ubuntu
sudo dnf install nmap      # Fedora
brew install nmap          # macOS
```

**2. Set up Python.** A ready-made virtualenv is included in `netpass/`:

```bash
source netpass/bin/activate
```

Or create your own:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install python-nmap
```

---

## Run

Just run it with no arguments — it auto-detects your local subnet and scans it:

```bash
python netpass.py
```

```
Scanning 192.168.1.0/24 ...

IP             HOSTNAME          MAC                VENDOR                OS               OPEN PORTS
----------------------------------------------------------------------------------------------------
192.168.1.1    router.local      F8:CA:59:D9:11:6B  NetComm Wireless      Linux 2.6 - 3.10 22,80,443
192.168.1.15   Living Room Echo  C0:95:CF:2F:1D:77  Amazon Technologies   Linux 5.0 - 5.5  -
192.168.1.50   -                 -                  -                     -                1080,8888

3 host(s) up.
```

You can also give it a specific target — a host, a CIDR range, or a hostname:

```bash
python netpass.py 10.0.0.0/24
python netpass.py 192.168.1.10
```

> **Note:** The `MAC`, `VENDOR`, and `OS` columns only fill in when you scan as
> root — see [Running as root](#running-as-root).

---

## How to use

### Options

| Flag | Description |
|------|-------------|
| `-p`, `--ports` | Ports to scan, e.g. `22,80,443` or `1-1024` (default: nmap's top ~1000). |
| `-s`, `--syn` | TCP SYN scan (`-sS`) — faster and stealthier. **Requires root.** |
| `-V`, `--version-detect` | Service/version detection (`-sV`). |
| `-O`, `--os-detect` | OS detection (`-O`). **Requires root.** |
| `-r`, `--report` | Print a per-device security report with fixes (enables service detection). |
| `--external` | Report what your network exposes to the internet (via Shodan InternetDB), then exit. |
| `--deep` | Deep CVE detection via nmap's vuln scripts; adds matched CVEs to the report. Slow. |
| `-o`, `--output FILE` | Also write results to a JSON file. |
| `--label MAC=NAME` | Save a custom name for a device, then exit. |
| `--list-labels` | List saved device names, then exit. |
| `--remove-label MAC` | Remove a saved device name, then exit. |
| `--check-wifi` | Rate the strength of this machine's Wi‑Fi password, then exit. |
| `--check-password PW` | Rate the strength of a password you supply, then exit. |
| `--update-db` | Force-refresh the MAC vendor database, then exit. |
| `--no-update-db` | Skip the automatic vendor-database refresh this run. |

Run `python netpass.py --help` for the full list.

### Running as root

`--syn` and `--os-detect` need root, and so does resolving MAC addresses and
vendors. Note that **`sudo` does not inherit the activated virtualenv** — so
`sudo python netpass.py` uses the system Python and fails with
`ModuleNotFoundError: nmap`. Point `sudo` at the venv's Python instead, and
combine the flags for the fullest picture of your network:

```bash
sudo ./netpass/bin/python netpass.py --syn -V -O
```

**Tip:** add an alias to `~/.bashrc` so you can just type `netpass`:

```bash
alias netpass='sudo /home/alfcon/Projects/Netpass/netpass/bin/python /home/alfcon/Projects/Netpass/netpass.py'
```

### Security report

Add `-r` to print a security report after the scan. For each device it lists
risky exposures — plaintext protocols (telnet, FTP), unauthenticated proxies,
exposed databases, outdated services, and more — with a concrete fix and a
severity (HIGH / MEDIUM / LOW), followed by a summary.

```bash
sudo ./netpass/bin/python netpass.py --syn -r
```

```
192.168.1.1  (router.local)
  [HIGH  ] Telnet enabled (port 23)
           Telnet transmits credentials and all data unencrypted.
           Fix: Disable telnet (in the device/router admin page) and use SSH.
  [MEDIUM] FTP exposed (port 21)
           ...
```

`-r` turns on service detection automatically so the advice reflects the actual
services running. On its own it's a heuristic assessment of exposed services —
treat it as a hardening checklist and verify against your own setup.

#### Deep CVE detection

Add `--deep` to also run nmap's vulnerability scripts (`vuln` + `vulners`),
which map detected service versions to known **CVEs** and actively check for
some vulnerabilities. Matched CVEs (with CVSS scores, most severe first) are
folded into the same report:

```bash
sudo ./netpass/bin/python netpass.py --syn --deep
```

```
192.168.1.20  (fileserver)
  [HIGH  ] CVEs reported by smb-vuln-ms17-010 (port 445)
           nmap script "smb-vuln-ms17-010" reports this host as VULNERABLE.
           Fix: Confirm and patch the affected service/firmware; see the CVEs.
  [HIGH  ] CVEs reported by vulners (port 22)
           nmap "vulners" flagged CVEs matching this service version:
           CVE-2016-10009 (7.5), CVE-2018-15473 (5.0), ...
           Fix: Update the service to a patched version; verify each CVE applies.
```

`--deep` is **much slower** (each host is capped at a 180 s nmap timeout) and
some checks need internet access. Version-based matches from `vulners` can
include false positives, so confirm each CVE actually applies to your device.

### Checking exposure from the internet

Everything above scans your *local* network. To see your network from the
**outside** — what an attacker on the internet can reach — use `--external`:

```bash
python netpass.py --external
```

It finds your public IP and looks it up in **Shodan's InternetDB** (a free
service that scans the whole internet), then reports which ports are reachable
from outside, any known CVEs on that IP, and how to close the exposure.

```
Public IP: 203.0.113.5
1 port(s) reachable from the internet:
  [MEDIUM] Port 30005 — Service exposed to the internet
           This port is reachable from the public internet.
           Fix: Remove any port-forwarding rule for it and disable UPnP ...
```

Scanning your own public IP from *inside* your network is unreliable (the router
loops it back), so this uses an external vantage point instead. Note that it
**sends your public IP to Shodan** to do the lookup, and the data reflects
Shodan's most recent scan, so it can be days or weeks old. "No open ports
visible" is the result you want.

### Naming your devices

Once you know what a device is, give it a name. It's keyed by MAC address, so it
sticks even if the device's IP changes, and it shows in the `HOSTNAME` column:

```bash
python netpass.py --label "C0:95:CF:2F:1D:77=Living Room Echo"
python netpass.py --list-labels
python netpass.py --remove-label C0:95:CF:2F:1D:77
```

Names are saved in `~/.config/netpass/labels.json`, separate from the vendor
database — so refreshing or resetting the database never affects them.

### Checking Wi‑Fi password strength

A weak Wi‑Fi password undermines every other protection, so NetPass can rate one
for you. A scan **cannot** read a Wi‑Fi password off the network, so these checks
work locally:

```bash
# Rate the password of the Wi‑Fi this machine is on (may need sudo to read it)
python netpass.py --check-wifi

# Rate any password you type in
python netpass.py --check-password "1234567890"
```

It flags common/default passwords, all-digit or sequential patterns, passwords
that match the network name, and anything too short, then suggests a fix. The
password is never printed back or sent anywhere.

### Vendor database

The `VENDOR` column comes from a local copy of the IEEE OUI database, cached at
`~/.cache/netpass/mac-vendors.json`. NetPass refreshes it automatically when it's
missing or over 7 days old (a ~4 MB download), which keeps vendor names current —
nmap's built-in list is often years out of date. If there's no network, it falls
back to the existing cache, so scans still work offline.

### Saving results

Use `-o` to write a JSON snapshot alongside the table. Re-scan later and diff the
files to spot new or changed devices:

```bash
python netpass.py -o results.json
```

Each host is recorded with its address, hostname, state, MAC, vendor, label, OS
guess, and open ports.

---

## Notes

- The `Modelfile` in this directory is unrelated to the scanner; it references a
  local GGUF model for [Ollama](https://ollama.com/).
