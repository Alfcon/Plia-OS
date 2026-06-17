# MAC Address Agent Design

**Date:** 2026-06-17
**Status:** Approved

## Goal

Add a "network" specialist agent that lets users view, randomize, set, and restore the MAC address of any network interface via natural language ("mask my MAC", "show my MAC address", "restore original MAC on wlan0").

## Architecture

```
modules/network_tools.py         — 4 @tool fns: show_mac, randomize_mac, set_mac, restore_mac
agents/network.py                — network_node: LLM parses intent → dispatches to tool fns
core/supervisor.py               — add "network" intent, keyword routes, graph node/edges
tests/test_network_tools.py      — tool unit tests (subprocess mocked)
tests/agents/test_network_agent.py — agent unit tests (LLM + tools mocked)
```

## Components

### `modules/network_tools.py`

Four `@tool`-decorated functions. All synchronous (called via `asyncio.to_thread` from the agent node, and directly available for LLM tool-calling via the respond node).

**Interface resolution** (shared helper `_resolve_interface(interface: str) -> str`):
- If `interface` is non-empty and exists in `ip -j link show`, use it.
- Otherwise auto-detect: first active (`UP`) non-loopback `ether` interface from `ip -j link show` JSON.
- Raises `ValueError` if none found.

**Original MAC storage**: `MemoryStore` facts table, key `original_mac_{iface}`. Uses existing `get_memory_store().remember()` / `recall_fact()`. Persists across restarts.

**Random MAC generation**: locally-administered unicast.
```python
import random
octets = [random.randint(0, 255) for _ in range(6)]
octets[0] = (octets[0] & 0xFE) | 0x02  # unicast + locally administered
```

**MAC change sequence** (requires root — Plia-OS runs as root):
```bash
ip link set dev <iface> down
ip link set dev <iface> address <mac>
ip link set dev <iface> up
```

**MAC format validation**: regex `^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$` before any `ip` call.

| Tool | Signature | Behaviour |
|------|-----------|-----------|
| `show_mac` | `(interface: str = "") -> str` | Returns `"<iface>: <mac>"` for given/detected interface |
| `randomize_mac` | `(interface: str = "") -> str` | Saves original to MemoryStore if not already saved; applies random MAC; returns old→new |
| `set_mac` | `(interface: str, mac_address: str) -> str` | Validates format; saves original if not already saved; applies MAC |
| `restore_mac` | `(interface: str = "") -> str` | Reads stored original from MemoryStore; applies it; returns confirmation. Error if no original stored. |

All tools return a plain string (success or error message).

### `agents/network.py`

Async LangGraph node `network_node(state: "AgentState") -> dict`.

LLM system prompt includes:
- Current UTC timestamp
- Comma-separated list of detected interfaces (from `ip -j link show`)
- Instruction to output JSON `{"action": "show"|"randomize"|"set"|"restore", "interface": "<name or null>", "mac": "<MAC or null>"}`

On LLM parse failure or missing required fields → returns fallback: `"[network]\nCouldn't parse that request. Try: 'show my MAC', 'randomize MAC on wlan0', 'set MAC to AA:BB:CC:DD:EE:FF', 'restore original MAC'."`.

On success → calls corresponding tool function via `asyncio.to_thread`, appends result to `tool_results`, sets `active_agent="network"`.

### `core/supervisor.py`

Add to `_KNOWN_INTENTS`:
```python
"network"
```

Add to `_KEYWORD_ROUTES`:
```python
"network": ["mac address", "change mac", "spoof mac", "mask mac", "randomize mac",
            "restore mac", "show mac", "my mac", "fake mac", "network address"],
```

Add to `_CLASSIFY_SYSTEM` description: `"network"` — use when user asks about MAC address or network interface identity.

Add node and edges in `_build_graph()` following the same pattern as reminder/home/calendar.

## Error Handling

| Scenario | Response |
|----------|----------|
| No active interface found | `"No active network interface found."` |
| Unknown interface name | `"Interface '<name>' not found."` |
| Invalid MAC format | `"Invalid MAC address format. Expected XX:XX:XX:XX:XX:XX."` |
| `ip` command fails | `"MAC change failed: <stderr>"` |
| `restore_mac` with no stored original | `"No original MAC stored for <iface>. Randomize first to save it."` |
| LLM parse error | Fallback message with usage examples |

## Testing

### `tests/test_network_tools.py`
Mock `subprocess.run` and `get_memory_store`. Tests:
- `show_mac("")` auto-detects interface, returns MAC string
- `show_mac("eth0")` returns MAC for named interface
- `randomize_mac("")` saves original to store, calls `ip link` down/set/up in order, returns old→new
- `randomize_mac` called twice on same interface does not overwrite stored original
- `set_mac("eth0", "AA:BB:CC:DD:EE:FF")` succeeds
- `set_mac("eth0", "not-a-mac")` returns format error without calling `ip`
- `restore_mac("")` reads stored original and applies it
- `restore_mac("")` with no stored original returns error string

### `tests/agents/test_network_agent.py`
Mock `call_llm` and tool functions. Tests:
- LLM returns invalid JSON → fallback message, `active_agent="network"`
- `action=show`, no interface → `show_mac("")` called
- `action=randomize`, `interface="wlan0"` → `randomize_mac("wlan0")` called
- `action=set`, `mac="AA:BB:CC:DD:EE:FF"` → `set_mac` called with correct args
- `action=restore` → `restore_mac` called
- Prior `tool_results` preserved (appended, not replaced)

## Constraints

- Plia-OS runs as root — no `sudo` prefix needed.
- `ip` binary assumed present (standard on all modern Linux systems).
- MAC change brings interface down momentarily — active connections drop briefly.
- No dashboard UI changes required.
