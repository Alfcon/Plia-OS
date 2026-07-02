# Research Agent System Design

**Goal:** Allow the LLM to create, edit, and delete custom agents via chat, and provide a research agent capability that searches a configurable list of academic/specialist sites, stores per-site credentials in the system keyring, and delivers results in one or more output formats (chat, TTS, browser page, text file).

**Architecture:** Four new subsystems — site registry, credential store, research tools, agent CRUD tools — each self-contained with a clear interface. Playwright-based authenticated browsing is explicitly Phase 2.

**Tech Stack:** Python, `keyring` library, `httpx`, AES-256 (`cryptography` package) for credential fallback, `xdg-open` for browser output, existing `core/registry.py` `@tool` decorator, existing `core/agent_store.py`.

---

## Global Constraints

- All tools use the existing `@tool` decorator from `core/registry.py`
- Agent names must match `^[a-z0-9-]+$` (enforced by `agent_store.save_agent`)
- Credentials never returned in plain text from any tool response
- `keyring` and `cryptography` added to `requirements.txt`; no other new mandatory deps
- Phase 2 (Playwright browser login) is out of scope for this spec
- All new storage files live under `~/.plia/` (respects `config.memory_dir`)

---

## File Structure

| File | Role |
|------|------|
| `core/research_site_store.py` | Site registry CRUD + 15 predefined sites |
| `core/credential_store.py` | Keyring-backed credential storage with AES fallback |
| `modules/research_tools.py` | LLM tools: site management, credentials, search, output |
| `modules/agent_tools.py` (extend) | Add `create_agent`, `edit_agent`, `delete_agent` |
| `tests/test_research_site_store.py` | Unit tests for site registry |
| `tests/test_credential_store.py` | Unit tests for credential store |
| `tests/test_research_tools.py` | Unit tests for research tools |
| `tests/test_agent_crud_tools.py` | Unit tests for agent CRUD tools |

---

## Section 1 — Site Registry (`core/research_site_store.py`)

### Storage

`~/.plia/research_sites.json` — a flat dict keyed by slug:

```json
{
  "google-scholar": {
    "name": "Google Scholar",
    "url": "https://scholar.google.com/",
    "search_url": "https://scholar.google.com/scholar?q={query}",
    "requires_login": false,
    "category": "academic",
    "credential_key": null
  }
}
```

Fields:
- `name` — display name
- `url` — base URL
- `search_url` — URL with `{query}` placeholder (URL-encoded at call time)
- `requires_login` — bool
- `category` — `"academic"` | `"dev"` | `"general"`
- `credential_key` — keyring service key string when `requires_login=true`, else `null`

### Predefined Sites (loaded on first access if file missing)

| Slug | Name | Requires Login |
|------|------|----------------|
| `google-scholar` | Google Scholar | No |
| `worldcat` | WorldCat | No |
| `researchgate` | ResearchGate | Yes |
| `bepress` | bepress Network | No |
| `google-books` | Google Books | No |
| `pubmed-central` | PubMed Central | No |
| `loc` | Library of Congress | No |
| `jstor` | JSTOR | Yes |
| `sciencedirect` | ScienceDirect | Yes |
| `academia-edu` | Academia.edu | Yes |
| `library-gov-au` | National Library of Australia | No |
| `ieee-xplore` | IEEE Xplore | Yes |
| `arxiv` | arXiv | No |
| `sci-hub` | Sci-Hub | No |

### Public API

```python
def list_sites() -> list[dict]
def get_site(slug: str) -> dict | None
def add_site(slug: str, name: str, url: str, search_url: str,
             requires_login: bool = False, category: str = "general") -> None
def remove_site(slug: str) -> bool
def set_credential_key(slug: str, key: str) -> None
def _default_sites() -> dict  # returns the 15 predefined entries
```

---

## Section 2 — Credential Store (`core/credential_store.py`)

### Primary: System Keyring

Uses `keyring.set_password(service="plia-research", username=site_slug, password=json_blob)` where `json_blob = json.dumps({"username": "...", "password": "..."})`.

### Failure Detection + Self-Healing

On any `keyring` exception:
1. Detect error type:
   - `keyring.errors.NoKeyringError` → no backend installed
   - `PermissionError` / `DBusException` → locked or headless environment
   - Any other → log as unknown
2. Record failure in config: `credential_backend = "file"` (via `update_config`)
3. Fall back to AES-256 encrypted file `~/.plia/credentials.enc`
   - Key derivation: `SHA-256(hostname + os.getlogin())` — machine-specific, no stored key
   - Uses `cryptography.fernet.Fernet`
4. On subsequent calls: if `config.credential_backend == "file"`, skip keyring entirely

### Fallback File Format

Fernet-encrypted bytes wrapping JSON:
```json
{"google-scholar": {"username": "...", "password": "..."}, ...}
```

### Public API

```python
def set_credentials(site_slug: str, username: str, password: str) -> str
    # Returns: "Stored in system keyring." or
    #          "Keyring unavailable ({reason}). Stored in encrypted file."

def get_credentials(site_slug: str) -> dict | None
    # Returns {"username": ..., "password": ...} or None

def remove_credentials(site_slug: str) -> bool

def has_credentials(site_slug: str) -> bool
```

---

## Section 3 — Research Tools (`modules/research_tools.py`)

### Site Management Tools

```python
@tool("List all registered research sites. Shows name, URL, whether login is required, "
      "and whether credentials are stored.")
def list_research_sites() -> str

@tool("Add a custom site to the research registry. slug: short identifier (lowercase, hyphens). "
      "name: display name. url: base URL. search_url: URL with {query} placeholder. "
      "requires_login: true/false.")
def add_research_site(slug: str, name: str, url: str, search_url: str,
                      requires_login: bool = False) -> str

@tool("Remove a site from the research registry by its slug.")
def remove_research_site(slug: str) -> str
```

### Credential Tools

```python
@tool("Store login credentials for a research site. site_slug matches the slug from "
      "list_research_sites. Credentials are stored in the system keyring or encrypted file.")
def set_site_credentials(site_slug: str, username: str, password: str) -> str

@tool("Confirm whether credentials are stored for a site. Never returns the password.")
def check_site_credentials(site_slug: str) -> str

@tool("Remove stored credentials for a site.")
def remove_site_credentials(site_slug: str) -> str
```

### Search Tool

```python
@tool("Search one or more research sites for a query. "
      "sites: comma-separated slugs (e.g. 'google-scholar,arxiv,pubmed-central'). "
      "Use 'all' to search all registered sites. "
      "output_formats: comma-separated from: chat, tts, browser, file. Default: chat. "
      "Returns snippets immediately. User can then ask to 'read result N' for full content.")
def research_search(query: str, sites: str = "all", output_formats: str = "chat") -> str
```

#### Search Behavior

For each site:
1. URL-encode `query`, substitute into `search_url`
2. Fetch with `httpx.get(..., headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)`
3. Extract results: parse `<a href>` links + surrounding text snippets via regex (title in `<h3>` or `<b>`, 200-char context window)
4. If `requires_login=true` and no credentials stored: include site in output with message `"[LOGIN REQUIRED — use set_site_credentials('{slug}', ...) to add credentials]"`
5. If `requires_login=true` and credentials stored: Phase 1 — attempt HTTP Basic Auth header; if site returns 401, note "Credentials stored but site requires browser login (Phase 2)"

#### Output Delivery

After collecting results:

- **`chat`** — always rendered; returns formatted markdown: `## Site Name\n1. [Title](url)\n   > snippet\n`
- **`tts`** — emits `speak` event: `"Found {N} results across {M} sites for '{query}'. Top results: {title1}, {title2}, {title3}."`
- **`browser`** — writes `/tmp/plia_research_{slug}_{timestamp}.html` with styled HTML table of all results, opens with `subprocess.Popen(["xdg-open", path])`
- **`file`** — writes `~/research/{query_slug}_{YYYY-MM-DD}.md` with full markdown results, creates `~/research/` if missing

Results include an index number so user can say "read result 3" → LLM calls `scrape_url(results[3].url)`.

---

## Section 4 — Agent CRUD Tools (`modules/agent_tools.py` additions)

```python
@tool("Create a new custom agent. name: slug (lowercase, hyphens). display_name: friendly name. "
      "description: what this agent does (shown in list). system_prompt: the agent's instructions. "
      "tool_names: comma-separated tool names the agent can use. "
      "keywords: comma-separated phrases that trigger this agent via keyword routing.")
def create_agent(name: str, system_prompt: str, display_name: str = "",
                 description: str = "", tool_names: str = "", keywords: str = "") -> str

@tool("Edit an existing custom agent. Only provided fields are updated.")
def edit_agent(name: str, display_name: str = "", description: str = "",
               system_prompt: str = "", tool_names: str = "", keywords: str = "") -> str

@tool("Delete a custom agent by name.")
def delete_agent(name: str) -> str
```

All three call `core.supervisor._reload_custom_agents()` after mutating the store so routing takes effect immediately without restart.

`tool_names` and `keywords` accept comma-separated strings; split on `,` and strip whitespace before storing as lists.

---

## Section 5 — Research Agent Creation Flow

**Trigger:** User says anything resembling "create a research agent for X" or "build an agent to search for Y".

**LLM behaviour (hybrid — extracts what it can, asks only about gaps):**

1. Extract topic from message
2. Call `list_research_sites()` — present the list, ask: "Which sites should I search? You can say 'all' or list slugs."
3. Ask: "How would you like results delivered? Choose one or more: chat, tts, browser, file."
4. If any chosen sites have `requires_login=true`: ask "ResearchGate, JSTOR [etc.] require login. Do you want to add credentials now?"
5. Call `create_agent(name="{topic-slug}-research", display_name="{Topic} Research Agent", system_prompt="You are a research agent specialising in {topic}. When asked to search, call research_search with the user's query and these default sites: {sites}. Default output formats: {formats}. Return results clearly numbered so the user can ask to read specific ones.", tool_names="research_search,scrape_url,list_research_sites,set_site_credentials", keywords="{topic},research {topic},{topic} papers")`
6. Immediately run: `run_agent("{topic-slug}-research", "Find all relevant peer-reviewed papers on {topic}")`

**The agent persists** — user can invoke it again any time via keyword routing or `run_agent`.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Site fetch times out | Include site in results with `"[Timeout after 15s]"` |
| Site returns 4xx/5xx | Include with `"[HTTP {code}]"` |
| `xdg-open` not available | Note in response: "Browser output unavailable on this platform" |
| `~/research/` not writable | Return error in response, skip file output |
| Keyring fails | Self-heal to encrypted file, report reason in `set_site_credentials` response |
| Agent name slug invalid | Return error: "Name must be lowercase letters, digits, and hyphens only" |
| `create_agent` with existing name | Return error: "Agent '{name}' already exists. Use edit_agent to update it." |

---

## Testing

- `test_research_site_store.py` — list/add/remove sites, default sites load, slug validation
- `test_credential_store.py` — set/get/remove/has, keyring mock, fallback to file when keyring raises, self-heal config write, machine key derivation
- `test_research_tools.py` — search with mocked httpx, multi-site, login-required sites, output format routing, file/browser output (mock xdg-open and file writes)
- `test_agent_crud_tools.py` — create/edit/delete, slug validation, supervisor reload called, tool_names/keywords parsing
