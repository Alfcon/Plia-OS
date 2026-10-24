# Plia-OS — Network Applications Documentation

Documentation and user guides for the network applications installed on this
computer and used by Plia-OS (the tools in **🔧 Tools → Network**). Each
application has its own subdirectory below.

| Application | What Plia-OS uses it for | Directory |
|-------------|--------------------------|-----------|
| NetworkManager (nmcli) | Everyday Wi-Fi / connection management, saved networks, USB dongle | `NetworkManager/` |
| aircrack-ng (airmon-ng, airodump-ng, aireplay-ng, aircrack-ng) | Wireless security testing — monitor mode, handshake capture, cracking | `aircrack-ng/` |
| reaver (+ wash) | WPS attacks and WPS-enabled AP scanning | `reaver/` |
| crunch | Wordlist generation for handshake cracking | `crunch/` |
| nmap | Local-network scanning and CVE scripts (via netpass) | `nmap/` |
| Tor | System-wide anonymous routing (kill switch, iptables NAT) | `Tor/` |
| iptables (netfilter) | Tor routing / kill-switch firewall rules | `iptables/` |
| netpass | Plia-OS's own defensive network-auditing program | `netpass/` |

## File types

- **`.txt`** — plain-text rendering of the program's `man` page (the built-in
  user guide shipped with the installed package). Rendered locally with
  `man … | col -b` (Tor rendered from the Debian man page, as the package is
  not installed here).
- **`.html` / `.md`** — official online documentation downloaded from the
  project's own website, Debian manpages, Kali tool pages, or the project's
  source repository.

## Sources

- **NetworkManager** — https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/
- **aircrack-ng** — https://github.com/aircrack-ng/aircrack-ng (README + `manpages/`), https://manpages.debian.org/bookworm/aircrack-ng/, https://www.kali.org/tools/aircrack-ng/, and the aircrack-ng.org wiki via the Wayback Machine
- **reaver** — https://github.com/t6x/reaver-wps-fork-t6x and https://manpages.debian.org/bookworm/reaver/
- **crunch** — https://manpages.debian.org/bookworm/crunch/ and https://www.kali.org/tools/crunch/
- **nmap** — https://nmap.org/book/man.html and https://nmap.org/docs.html
- **Tor** — https://manpages.debian.org/bookworm/tor/ and https://support.torproject.org/
- **iptables** — https://manpages.debian.org/bookworm/iptables/ and https://www.netfilter.org/documentation/
- **netpass** — local project README (`/home/alfcon/Projects/Netpass/README.md`)

> **Note on aircrack-ng.org**: the project's DokuWiki (`/doku.php`) returns
> HTTP 500 (the bare landing page at `/` still loads). Its wiki pages were
> therefore retrieved from the Internet Archive Wayback Machine, and the
> authoritative docs from the GitHub repository (`README.md`, `INSTALLING`,
> `manpages/`) were downloaded as well.
