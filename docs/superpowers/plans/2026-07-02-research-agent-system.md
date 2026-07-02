# Research Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a research agent system to Plia-OS: a configurable site registry, keyring-backed credential store, LLM tools for searching academic/specialist sites, and LLM tools to create/edit/delete custom agents from chat.

**Architecture:** Four tasks, each independent and testable. Site registry and credential store are pure data layers (`core/`). Research tools and agent CRUD tools (`modules/`) depend on those layers. All tools auto-discovered via existing `@tool` decorator. No new routes, no new endpoints.

**Tech Stack:** Python 3.12, `keyring`, `cryptography` (Fernet), `httpx` (already a dep), existing `core/registry.py` `@tool` decorator, `core/agent_store.py`, `core/supervisor._reload_custom_agents`.

## Global Constraints

- All tools use `@tool` decorator from `core/registry.py` — same pattern as `modules/memory_tools.py`
- Agent names must match `^[a-z0-9-]+$` — validated by both tool and `agent_store.save_agent`
- Credentials NEVER returned in plain text from any tool response
- `keyring` and `cryptography` added to `pyproject.toml` `[project.dependencies]` — no other new mandatory deps
- Phase 2 (Playwright browser login) out of scope
- All storage files under `~/.plia/` — determined by `PLIA_CONFIG_FILE` env var, same pattern as `core/agent_store.py`
- `research_search` must be `async def` — it awaits `events.emit("speak", ...)` for TTS output
- `create_agent`, `edit_agent`, `delete_agent` are sync — they do no I/O that needs awaiting
- Tests use `autouse` fixtures from `conftest.py`: `isolate_config_file`, `reset_registry`, `reset_events` — these run automatically; don't re-declare them
- `asyncio_mode = "auto"` in pytest config — async tests need `@pytest.mark.asyncio` OR just `async def` (both work)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `core/research_site_store.py` | Create | Site registry CRUD + 14 predefined sites |
| `core/credential_store.py` | Create | Keyring storage + AES-256 file fallback |
| `core/config.py` | Modify | Add `credential_backend: str = "keyring"` field + constraint |
| `pyproject.toml` | Modify | Add `keyring` and `cryptography` to deps |
| `modules/research_tools.py` | Create | LLM tools: site mgmt + credentials + search + output |
| `modules/agent_tools.py` | Modify | Add `create_agent`, `edit_agent`, `delete_agent` |
| `tests/test_research_site_store.py` | Create | Site registry unit tests |
| `tests/test_credential_store.py` | Create | Credential store unit tests |
| `tests/test_research_tools.py` | Create | Research tool unit tests |
| `tests/test_agent_crud_tools.py` | Create | Agent CRUD tool unit tests |

---

### Task 1: Site Registry

**Files:**
- Create: `core/research_site_store.py`
- Create: `tests/test_research_site_store.py`

**Interfaces:**
- Produces:
  - `list_sites() -> list[dict]` — each dict has keys: `slug`, `name`, `url`, `search_url`, `requires_login: bool`, `category: str`, `credential_key: str | None`
  - `get_site(slug: str) -> dict | None`
  - `add_site(slug: str, name: str, url: str, search_url: str, requires_login: bool = False, category: str = "general") -> None`
  - `remove_site(slug: str) -> bool`
  - `set_credential_key(slug: str, key: str) -> None`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_research_site_store.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _make_store(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    return sites_file


def test_list_sites_returns_defaults(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import list_sites
        sites = list_sites()
    assert len(sites) == 14
    slugs = [s["slug"] for s in sites]
    assert "google-scholar" in slugs
    assert "arxiv" in slugs
    assert "sci-hub" in slugs


def test_get_site_returns_dict(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import get_site
        site = get_site("arxiv")
    assert site is not None
    assert site["name"] == "arXiv"
    assert "{query}" in site["search_url"]
    assert site["requires_login"] is False


def test_get_site_unknown_returns_none(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import get_site
        assert get_site("does-not-exist") is None


def test_add_site_persists(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import add_site, get_site
        add_site(
            slug="test-site",
            name="Test Site",
            url="https://example.com/",
            search_url="https://example.com/search?q={query}",
            requires_login=True,
            category="dev",
        )
        site = get_site("test-site")
    assert site is not None
    assert site["name"] == "Test Site"
    assert site["requires_login"] is True
    assert site["category"] == "dev"


def test_remove_site_returns_true_for_existing(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import remove_site, get_site
        removed = remove_site("arxiv")
        assert removed is True
        assert get_site("arxiv") is None


def test_remove_site_returns_false_for_missing(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import remove_site
        assert remove_site("no-such-site") is False


def test_set_credential_key_updates_site(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import set_credential_key, get_site
        set_credential_key("jstor", "plia-research")
        site = get_site("jstor")
    assert site["credential_key"] == "plia-research"


def test_list_sites_includes_slug_field(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import list_sites
        sites = list_sites()
    for s in sites:
        assert "slug" in s
        assert s["slug"] != ""
```

- [ ] **Step 2: Run to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_research_site_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.research_site_store'`

- [ ] **Step 3: Implement `core/research_site_store.py`**

```python
from __future__ import annotations

import json
import os
from pathlib import Path

_SITES_FILE = Path(
    os.environ.get(
        "PLIA_RESEARCH_SITES_FILE",
        str(
            Path(
                os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
            ).parent
            / "research_sites.json"
        ),
    )
)

_SLUG_RE_STR = r"^[a-z0-9-]+$"


def _default_sites() -> dict:
    return {
        "google-scholar": {
            "name": "Google Scholar",
            "url": "https://scholar.google.com/",
            "search_url": "https://scholar.google.com/scholar?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "worldcat": {
            "name": "WorldCat",
            "url": "https://www.worldcat.org/",
            "search_url": "https://www.worldcat.org/search?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "researchgate": {
            "name": "ResearchGate",
            "url": "https://www.researchgate.net/",
            "search_url": "https://www.researchgate.net/search?q={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "bepress": {
            "name": "bepress Network",
            "url": "https://works.bepress.com/",
            "search_url": "https://works.bepress.com/search/?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "google-books": {
            "name": "Google Books",
            "url": "https://books.google.com/",
            "search_url": "https://www.google.com/search?tbm=bks&q={query}",
            "requires_login": False,
            "category": "general",
            "credential_key": None,
        },
        "pubmed-central": {
            "name": "PubMed Central",
            "url": "https://www.ncbi.nlm.nih.gov/pmc/",
            "search_url": "https://www.ncbi.nlm.nih.gov/pmc/search/?query={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "loc": {
            "name": "Library of Congress",
            "url": "https://www.loc.gov/",
            "search_url": "https://www.loc.gov/search/?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "jstor": {
            "name": "JSTOR",
            "url": "https://www.jstor.org/",
            "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "sciencedirect": {
            "name": "ScienceDirect",
            "url": "https://www.sciencedirect.com/",
            "search_url": "https://www.sciencedirect.com/search?qs={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "academia-edu": {
            "name": "Academia.edu",
            "url": "https://www.academia.edu/",
            "search_url": "https://www.academia.edu/search?q={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "library-gov-au": {
            "name": "National Library of Australia",
            "url": "https://catalogue.nla.gov.au/",
            "search_url": "https://catalogue.nla.gov.au/Search/Home?lookfor={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "ieee-xplore": {
            "name": "IEEE Xplore",
            "url": "https://ieeexplore.ieee.org/",
            "search_url": "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "arxiv": {
            "name": "arXiv",
            "url": "https://arxiv.org/",
            "search_url": "https://arxiv.org/search/?searchtype=all&query={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "sci-hub": {
            "name": "Sci-Hub",
            "url": "https://sci-hub.in/",
            "search_url": "https://sci-hub.in/{query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
    }


def _load() -> dict:
    try:
        return json.loads(_SITES_FILE.read_text())
    except Exception:
        return _default_sites()


def _save(data: dict) -> None:
    _SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SITES_FILE.write_text(json.dumps(data, indent=2))


def list_sites() -> list[dict]:
    data = _load()
    return [{"slug": slug, **entry} for slug, entry in sorted(data.items())]


def get_site(slug: str) -> dict | None:
    data = _load()
    if slug not in data:
        return None
    return {"slug": slug, **data[slug]}


def add_site(
    slug: str,
    name: str,
    url: str,
    search_url: str,
    requires_login: bool = False,
    category: str = "general",
) -> None:
    data = _load()
    data[slug] = {
        "name": name,
        "url": url,
        "search_url": search_url,
        "requires_login": requires_login,
        "category": category,
        "credential_key": None,
    }
    _save(data)


def remove_site(slug: str) -> bool:
    data = _load()
    if slug not in data:
        return False
    del data[slug]
    _save(data)
    return True


def set_credential_key(slug: str, key: str) -> None:
    data = _load()
    if slug in data:
        data[slug]["credential_key"] = key
        _save(data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_research_site_store.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add core/research_site_store.py tests/test_research_site_store.py
git commit -m "feat(research): add site registry with 14 predefined academic sites"
```

---

### Task 2: Credential Store + Config + Deps

**Files:**
- Create: `core/credential_store.py`
- Modify: `core/config.py` (add `credential_backend` field + constraint)
- Modify: `pyproject.toml` (add `keyring`, `cryptography` deps)
- Create: `tests/test_credential_store.py`

**Interfaces:**
- Consumes: `core/config.py` → `get_config()`, `update_config(**kwargs)`
- Produces:
  - `set_credentials(site_slug: str, username: str, password: str) -> str`
  - `get_credentials(site_slug: str) -> dict | None` — `{"username": str, "password": str}` or `None`
  - `remove_credentials(site_slug: str) -> bool`
  - `has_credentials(site_slug: str) -> bool`

- [ ] **Step 1: Add deps to `pyproject.toml`**

In `pyproject.toml`, in `[project]` `dependencies` list, add after the last item:

```toml
    "keyring>=25.0",
    "cryptography>=42.0",
```

Full updated dependencies block (replace existing):

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "sounddevice>=0.5",
    "numpy>=1.26",
    "openwakeword>=0.4",
    "faster-whisper>=1.0",
    "kokoro>=0.9",
    "chatterbox-tts>=0.1",
    "scipy>=1.13",
    "langgraph>=0.2",
    "chromadb>=0.4",
    "ddgs>=0.1",
    "icalendar>=5.0",
    "psutil>=5.9",
    "keyring>=25.0",
    "cryptography>=42.0",
]
```

Then install:
```bash
source .venv/bin/activate && pip install -e . --no-deps && pip install keyring cryptography
```

- [ ] **Step 2: Add `credential_backend` to `core/config.py`**

Find the `tool_guard_list` field (last field before end of dataclass, around line 127). Add after it:

```python
    # Credential store backend
    credential_backend: str = "keyring"
```

Then find `_LITERAL_CONSTRAINTS` dict (around line 142) and add:

```python
    "credential_backend": ("keyring", "file"),
```

The dict currently has entries like `"tts_engine": (...)`. Add the new entry alongside them.

- [ ] **Step 3: Write failing credential store tests**

```python
# tests/test_credential_store.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_set_credentials_stores_in_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.set_password") as mock_set, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("google-scholar", "user1", "pass1")

    mock_set.assert_called_once_with(
        "plia-research",
        "google-scholar",
        json.dumps({"username": "user1", "password": "pass1"}),
    )
    assert "system keyring" in result


def test_set_credentials_falls_back_to_file_on_no_keyring(tmp_path):
    import keyring.errors
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.set_password", side_effect=keyring.errors.NoKeyringError()), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store.update_config") as mock_update, \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("arxiv", "user2", "pass2")

    mock_update.assert_called_once_with(credential_backend="file")
    assert "encrypted file" in result
    assert cred_file.exists()


def test_set_credentials_uses_file_when_backend_is_file(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "file"

    with patch("keyring.set_password") as mock_set, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials
        result = set_credentials("jstor", "u", "p")

    mock_set.assert_not_called()
    assert cred_file.exists()


def test_get_credentials_from_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"
    blob = json.dumps({"username": "alice", "password": "secret"})

    with patch("keyring.get_password", return_value=blob), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import get_credentials
        creds = get_credentials("google-scholar")

    assert creds == {"username": "alice", "password": "secret"}


def test_get_credentials_returns_none_when_not_found(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import get_credentials
        assert get_credentials("unknown-site") is None


def test_roundtrip_file_backend(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "file"

    with patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store.update_config"), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import set_credentials, get_credentials
        set_credentials("jstor", "bob", "hunter2")
        creds = get_credentials("jstor")

    assert creds == {"username": "bob", "password": "hunter2"}


def test_has_credentials_true(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"
    blob = json.dumps({"username": "x", "password": "y"})

    with patch("keyring.get_password", return_value=blob), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import has_credentials
        assert has_credentials("jstor") is True


def test_has_credentials_false(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import has_credentials
        assert has_credentials("no-site") is False


def test_remove_credentials_keyring(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value='{"username":"a","password":"b"}'), \
         patch("keyring.delete_password") as mock_del, \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import remove_credentials
        result = remove_credentials("google-scholar")

    mock_del.assert_called_once_with("plia-research", "google-scholar")
    assert result is True


def test_remove_credentials_returns_false_when_not_found(tmp_path):
    cred_file = tmp_path / "credentials.enc"
    mock_cfg = MagicMock()
    mock_cfg.credential_backend = "keyring"

    with patch("keyring.get_password", return_value=None), \
         patch("core.credential_store.get_config", return_value=mock_cfg), \
         patch("core.credential_store._CRED_FILE", cred_file):
        from core.credential_store import remove_credentials
        assert remove_credentials("missing") is False
```

- [ ] **Step 4: Run to verify they fail**

```bash
pytest tests/test_credential_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.credential_store'`

- [ ] **Step 5: Implement `core/credential_store.py`**

```python
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE = "plia-research"

_CRED_FILE = Path(
    os.environ.get(
        "PLIA_CRED_FILE",
        str(
            Path(
                os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
            ).parent
            / "credentials.enc"
        ),
    )
)


def _derive_key() -> bytes:
    try:
        user = getpass.getuser()
    except Exception:
        user = "plia"
    raw = (socket.gethostname() + user).encode()
    digest = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(digest)


def _load_file() -> dict:
    path = _CRED_FILE
    if not path.exists():
        return {}
    try:
        from cryptography.fernet import Fernet
        return json.loads(Fernet(_derive_key()).decrypt(path.read_bytes()))
    except Exception:
        return {}


def _save_file(data: dict) -> None:
    from cryptography.fernet import Fernet
    path = _CRED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet(_derive_key()).encrypt(json.dumps(data).encode()))


def _classify_keyring_error(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "nokeyring" in name.lower() or "nobackend" in name.lower():
        return "no keyring backend installed"
    if "permission" in name.lower() or "dbus" in name.lower() or "locked" in msg:
        return "keyring locked or headless environment"
    return f"keyring error: {name}"


def set_credentials(site_slug: str, username: str, password: str) -> str:
    from core.config import get_config, update_config
    cfg = get_config()
    blob = json.dumps({"username": username, "password": password})

    if cfg.credential_backend == "file":
        data = _load_file()
        data[site_slug] = {"username": username, "password": password}
        _save_file(data)
        return f"Stored credentials for '{site_slug}' in encrypted file."

    try:
        import keyring
        keyring.set_password(_SERVICE, site_slug, blob)
        return f"Stored credentials for '{site_slug}' in system keyring."
    except Exception as exc:
        reason = _classify_keyring_error(exc)
        logger.warning("Keyring unavailable (%s), falling back to encrypted file", reason)
        update_config(credential_backend="file")
        data = _load_file()
        data[site_slug] = {"username": username, "password": password}
        _save_file(data)
        return f"Keyring unavailable ({reason}). Stored credentials for '{site_slug}' in encrypted file."


def get_credentials(site_slug: str) -> dict | None:
    from core.config import get_config
    cfg = get_config()

    if cfg.credential_backend == "file":
        data = _load_file()
        return data.get(site_slug)

    try:
        import keyring
        blob = keyring.get_password(_SERVICE, site_slug)
        if blob is None:
            return None
        return json.loads(blob)
    except Exception:
        data = _load_file()
        return data.get(site_slug)


def has_credentials(site_slug: str) -> bool:
    return get_credentials(site_slug) is not None


def remove_credentials(site_slug: str) -> bool:
    from core.config import get_config
    cfg = get_config()

    if cfg.credential_backend == "file":
        data = _load_file()
        if site_slug not in data:
            return False
        del data[site_slug]
        _save_file(data)
        return True

    try:
        import keyring
        if keyring.get_password(_SERVICE, site_slug) is None:
            return False
        keyring.delete_password(_SERVICE, site_slug)
        return True
    except Exception:
        data = _load_file()
        if site_slug not in data:
            return False
        del data[site_slug]
        _save_file(data)
        return True
```

- [ ] **Step 6: Run credential tests to verify they pass**

```bash
pytest tests/test_credential_store.py -v
```

Expected: `10 passed`

- [ ] **Step 7: Run full suite to verify nothing broken**

```bash
pytest --tb=short -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add core/credential_store.py core/config.py pyproject.toml tests/test_credential_store.py
git commit -m "feat(research): add credential store with keyring + AES-256 fallback"
```

---

### Task 3: Research Tools — Site Management + Credentials

**Files:**
- Create: `modules/research_tools.py` (site + credential tools only; search added in Task 4)
- Create: `tests/test_research_tools.py` (site + credential tool tests only)

**Interfaces:**
- Consumes:
  - `core.research_site_store.list_sites() -> list[dict]`
  - `core.research_site_store.add_site(...) -> None`
  - `core.research_site_store.remove_site(slug) -> bool`
  - `core.credential_store.set_credentials(slug, user, pw) -> str`
  - `core.credential_store.has_credentials(slug) -> bool`
  - `core.credential_store.remove_credentials(slug) -> bool`
- Produces (tool functions):
  - `list_research_sites() -> str`
  - `add_research_site(slug, name, url, search_url, requires_login) -> str`
  - `remove_research_site(slug) -> str`
  - `set_site_credentials(site_slug, username, password) -> str`
  - `check_site_credentials(site_slug) -> str`
  - `remove_site_credentials(site_slug) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_research_tools.py
import pytest
from unittest.mock import patch, MagicMock


def test_list_research_sites_shows_all(tmp_path):
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.credential_store.has_credentials", return_value=False):
        from modules.research_tools import list_research_sites
        result = list_research_sites()
    assert "arXiv" in result
    assert "JSTOR" in result
    assert "login required" in result.lower()


def test_list_research_sites_shows_credentials_stored(tmp_path):
    mock_sites = [
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.credential_store.has_credentials", return_value=True):
        from modules.research_tools import list_research_sites
        result = list_research_sites()
    assert "credentials stored" in result.lower()


def test_add_research_site_calls_store():
    with patch("core.research_site_store.add_site") as mock_add:
        from modules.research_tools import add_research_site
        result = add_research_site(
            slug="my-site",
            name="My Site",
            url="https://mysite.com/",
            search_url="https://mysite.com/search?q={query}",
            requires_login=False,
        )
    mock_add.assert_called_once_with(
        slug="my-site",
        name="My Site",
        url="https://mysite.com/",
        search_url="https://mysite.com/search?q={query}",
        requires_login=False,
    )
    assert "my-site" in result
    assert "added" in result.lower()


def test_remove_research_site_calls_store():
    with patch("core.research_site_store.remove_site", return_value=True):
        from modules.research_tools import remove_research_site
        result = remove_research_site("arxiv")
    assert "arxiv" in result
    assert "removed" in result.lower()


def test_remove_research_site_not_found():
    with patch("core.research_site_store.remove_site", return_value=False):
        from modules.research_tools import remove_research_site
        result = remove_research_site("no-such")
    assert "not found" in result.lower() or "no site" in result.lower()


def test_set_site_credentials_calls_credential_store():
    with patch("core.credential_store.set_credentials", return_value="Stored in system keyring.") as mock_set, \
         patch("core.research_site_store.get_site", return_value={"slug": "jstor", "name": "JSTOR", "requires_login": True, "credential_key": None}), \
         patch("core.research_site_store.set_credential_key"):
        from modules.research_tools import set_site_credentials
        result = set_site_credentials("jstor", "alice", "secret123")
    mock_set.assert_called_once_with("jstor", "alice", "secret123")
    assert "jstor" in result.lower()


def test_set_site_credentials_unknown_site():
    with patch("core.research_site_store.get_site", return_value=None):
        from modules.research_tools import set_site_credentials
        result = set_site_credentials("unknown-slug", "u", "p")
    assert "not found" in result.lower() or "no site" in result.lower()


def test_check_site_credentials_found():
    with patch("core.credential_store.has_credentials", return_value=True):
        from modules.research_tools import check_site_credentials
        result = check_site_credentials("jstor")
    assert "stored" in result.lower()
    assert "jstor" in result


def test_check_site_credentials_not_found():
    with patch("core.credential_store.has_credentials", return_value=False):
        from modules.research_tools import check_site_credentials
        result = check_site_credentials("jstor")
    assert "no credentials" in result.lower() or "not stored" in result.lower()


def test_remove_site_credentials_success():
    with patch("core.credential_store.remove_credentials", return_value=True):
        from modules.research_tools import remove_site_credentials
        result = remove_site_credentials("jstor")
    assert "removed" in result.lower()
    assert "jstor" in result


def test_remove_site_credentials_not_found():
    with patch("core.credential_store.remove_credentials", return_value=False):
        from modules.research_tools import remove_site_credentials
        result = remove_site_credentials("jstor")
    assert "no credentials" in result.lower() or "not found" in result.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_research_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.research_tools'`

- [ ] **Step 3: Implement `modules/research_tools.py` (site + credential tools only)**

```python
from __future__ import annotations

from core.registry import tool


@tool(
    "List all registered research sites. Shows name, URL, login requirement, "
    "and whether credentials are stored."
)
def list_research_sites() -> str:
    from core.research_site_store import list_sites
    from core.credential_store import has_credentials
    sites = list_sites()
    if not sites:
        return "No research sites registered."
    lines = []
    for s in sites:
        login = ""
        if s["requires_login"]:
            stored = has_credentials(s["slug"])
            login = " [login required — credentials stored]" if stored else " [login required — no credentials stored]"
        lines.append(f"- **{s['slug']}**: {s['name']} ({s['category']}){login}")
        lines.append(f"  Search: {s['search_url']}")
    return "\n".join(lines)


@tool(
    "Add a custom site to the research registry. "
    "slug: short identifier (lowercase, hyphens only, e.g. 'my-journal'). "
    "name: display name. url: base URL. search_url: URL with {query} placeholder. "
    "requires_login: true if the site needs credentials."
)
def add_research_site(
    slug: str,
    name: str,
    url: str,
    search_url: str,
    requires_login: bool = False,
) -> str:
    from core.research_site_store import add_site
    add_site(slug=slug, name=name, url=url, search_url=search_url, requires_login=requires_login)
    return f"Site '{slug}' ({name}) added to research registry."


@tool("Remove a site from the research registry by its slug.")
def remove_research_site(slug: str) -> str:
    from core.research_site_store import remove_site
    if remove_site(slug):
        return f"Site '{slug}' removed from research registry."
    return f"No site with slug '{slug}' found."


@tool(
    "Store login credentials for a research site. "
    "site_slug must match a slug from list_research_sites. "
    "Credentials are stored in the system keyring or an encrypted file — never in plain text."
)
def set_site_credentials(site_slug: str, username: str, password: str) -> str:
    from core.research_site_store import get_site, set_credential_key
    from core.credential_store import set_credentials
    site = get_site(site_slug)
    if site is None:
        return f"No site with slug '{site_slug}' found. Run list_research_sites to see available sites."
    result = set_credentials(site_slug, username, password)
    set_credential_key(site_slug, "plia-research")
    return f"{result} Credentials for '{site_slug}' ({site['name']}) are ready."


@tool(
    "Check whether credentials are stored for a research site. "
    "Never returns the password — only confirms presence or absence."
)
def check_site_credentials(site_slug: str) -> str:
    from core.credential_store import has_credentials
    if has_credentials(site_slug):
        return f"Credentials for '{site_slug}' are stored."
    return f"No credentials stored for '{site_slug}'."


@tool("Remove stored credentials for a research site.")
def remove_site_credentials(site_slug: str) -> str:
    from core.credential_store import remove_credentials
    if remove_credentials(site_slug):
        return f"Credentials for '{site_slug}' removed."
    return f"No credentials found for '{site_slug}'."
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_research_tools.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/research_tools.py tests/test_research_tools.py
git commit -m "feat(research): add site management and credential LLM tools"
```

---

### Task 4: Research Search Tool

**Files:**
- Modify: `modules/research_tools.py` (append `research_search` function)
- Modify: `tests/test_research_tools.py` (append search tests)

**Interfaces:**
- Consumes:
  - `core.research_site_store.list_sites() -> list[dict]`
  - `core.research_site_store.get_site(slug) -> dict | None`
  - `core.credential_store.has_credentials(slug) -> bool`
  - `core.credential_store.get_credentials(slug) -> dict | None`
  - `core.events.emit("speak", {"message": str})` — for TTS output
  - `httpx.get(url, headers, timeout, follow_redirects)` — for HTTP fetches
- Produces:
  - `research_search(query: str, sites: str = "all", output_formats: str = "chat") -> str` (async tool)

- [ ] **Step 1: Write failing tests (append to `tests/test_research_tools.py`)**

Add these tests after the existing ones in `tests/test_research_tools.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_research_search_returns_chat_results():
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?searchtype=all&query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/2301.00001">MHD Saltwater Research</a> Abstract about magnetohydrodynamics.'

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("MHD saltwater generators", sites="arxiv", output_formats="chat")

    assert "arXiv" in result
    assert "arxiv.org" in result


@pytest.mark.asyncio
async def test_research_search_login_required_no_creds():
    mock_sites = [
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test query", sites="jstor", output_formats="chat")

    assert "LOGIN REQUIRED" in result or "login required" in result.lower()
    assert "set_site_credentials" in result


@pytest.mark.asyncio
async def test_research_search_timeout_handled():
    import httpx
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", side_effect=httpx.TimeoutException("timeout")), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test", sites="arxiv", output_formats="chat")

    assert "Timeout" in result or "timeout" in result.lower()


@pytest.mark.asyncio
async def test_research_search_http_error_handled():
    import httpx
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = ""

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test", sites="arxiv", output_formats="chat")

    assert "403" in result or "HTTP" in result


@pytest.mark.asyncio
async def test_research_search_tts_output_emits_speak():
    from unittest.mock import AsyncMock
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/001">Title One</a> Some context here.'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html
    mock_emit = AsyncMock()

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", return_value=mock_response), \
         patch("core.events.emit", mock_emit):
        from modules.research_tools import research_search
        await research_search("test query", sites="arxiv", output_formats="chat,tts")

    speak_calls = [c for c in mock_emit.call_args_list if c.args[0] == "speak"]
    assert len(speak_calls) == 1
    assert "test query" in speak_calls[0].args[1]["message"]


@pytest.mark.asyncio
async def test_research_search_file_output_writes_file(tmp_path):
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/001">Paper Title</a> Abstract text here.'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock), \
         patch("modules.research_tools._RESEARCH_DIR", tmp_path):
        from modules.research_tools import research_search
        result = await research_search("paper topic", sites="arxiv", output_formats="chat,file")

    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    assert "Paper Title" in written[0].read_text()


@pytest.mark.asyncio
async def test_research_search_browser_output_calls_xdg_open(tmp_path):
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/001">Browser Title</a>'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("httpx.get", return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock), \
         patch("subprocess.Popen") as mock_popen, \
         patch("modules.research_tools._RESEARCH_DIR", tmp_path):
        from modules.research_tools import research_search
        await research_search("browser test", sites="arxiv", output_formats="chat,browser")

    assert mock_popen.called
    args = mock_popen.call_args[0][0]
    assert args[0] == "xdg-open"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_research_tools.py::test_research_search_returns_chat_results -v
```

Expected: `AttributeError: module 'modules.research_tools' has no attribute 'research_search'`

- [ ] **Step 3: Append `research_search` to `modules/research_tools.py`**

Add after the existing `remove_site_credentials` function:

```python
import re as _re
import subprocess
from datetime import date
from pathlib import Path

_RESEARCH_DIR = Path.home() / "research"


def _extract_snippets(html: str, max_results: int = 10) -> list[dict]:
    html = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
    pattern = _re.compile(
        r'<a[^>]+href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>',
        _re.DOTALL | _re.IGNORECASE,
    )
    results = []
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        text = _re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href.startswith("http") or len(text) < 5 or len(text) > 300:
            continue
        raw_after = html[m.end():m.end() + 600]
        snippet = _re.sub(r"<[^>]+>", " ", raw_after)
        snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": text, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _query_slug(query: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]


def _results_to_markdown(query: str, all_results: dict) -> str:
    lines = [f"# Research: {query}\n"]
    idx = 1
    for site_name, results in all_results.items():
        lines.append(f"\n## {site_name}\n")
        if isinstance(results, str):
            lines.append(results)
            continue
        for r in results:
            lines.append(f"{idx}. [{r['title']}]({r['url']})")
            if r["snippet"]:
                lines.append(f"   > {r['snippet']}\n")
            idx += 1
    return "\n".join(lines)


def _results_to_html(query: str, all_results: dict) -> str:
    rows = ""
    idx = 1
    for site_name, results in all_results.items():
        if isinstance(results, str):
            rows += f'<tr><td>{idx}</td><td>{site_name}</td><td colspan="2"><em>{results}</em></td></tr>'
            idx += 1
            continue
        for r in results:
            title_cell = f'<a href="{r["url"]}">{r["title"]}</a>'
            rows += f"<tr><td>{idx}</td><td>{site_name}</td><td>{title_cell}</td><td>{r['snippet']}</td></tr>"
            idx += 1
    return (
        f"<!DOCTYPE html><html><head><title>Research: {query}</title>"
        "<style>body{font-family:sans-serif;max-width:1200px;margin:2em auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.5em;text-align:left}"
        "th{background:#eee}a{color:#0066cc}</style></head><body>"
        f"<h1>Research: {query}</h1>"
        "<table><tr><th>#</th><th>Site</th><th>Title</th><th>Snippet</th></tr>"
        f"{rows}</table></body></html>"
    )


@tool(
    "Search one or more research sites for a query. "
    "sites: comma-separated slugs (e.g. 'google-scholar,arxiv') or 'all' for all registered sites. "
    "output_formats: comma-separated subset of: chat, tts, browser, file. Default: chat. "
    "Returns numbered results — user can say 'read result 3' to get full content via scrape_url."
)
async def research_search(
    query: str,
    sites: str = "all",
    output_formats: str = "chat",
) -> str:
    import httpx
    from urllib.parse import quote_plus
    from core.research_site_store import list_sites, get_site
    from core.credential_store import has_credentials, get_credentials
    from core import events

    formats = {f.strip() for f in output_formats.split(",") if f.strip()}
    encoded = quote_plus(query)

    if sites.strip().lower() == "all":
        site_slugs = [s["slug"] for s in list_sites()]
    else:
        site_slugs = [s.strip() for s in sites.split(",") if s.strip()]

    all_results: dict = {}
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    for slug in site_slugs:
        site = get_site(slug)
        if site is None:
            all_results[slug] = f"[Unknown site '{slug}']"
            continue

        site_name = site["name"]

        if site["requires_login"] and not has_credentials(slug):
            all_results[site_name] = (
                f"[LOGIN REQUIRED — use set_site_credentials('{slug}', username, password) to add credentials]"
            )
            continue

        url = site["search_url"].replace("{query}", encoded)
        request_kwargs: dict = {"headers": headers, "timeout": 15, "follow_redirects": True}

        if site["requires_login"]:
            creds = get_credentials(slug)
            if creds:
                request_kwargs["auth"] = (creds["username"], creds["password"])

        try:
            resp = httpx.get(url, **request_kwargs)
        except httpx.TimeoutException:
            all_results[site_name] = "[Timeout after 15s]"
            continue
        except Exception as exc:
            all_results[site_name] = f"[Fetch error: {type(exc).__name__}]"
            continue

        if resp.status_code != 200:
            if resp.status_code == 401 and site["requires_login"]:
                all_results[site_name] = (
                    f"[HTTP 401 — credentials stored but site requires browser login (Phase 2)]"
                )
            else:
                all_results[site_name] = f"[HTTP {resp.status_code}]"
            continue

        snippets = _extract_snippets(resp.text)
        all_results[site_name] = snippets if snippets else [{"title": "(no results parsed)", "url": url, "snippet": ""}]

    # Build chat output (always)
    chat_lines = [f"## Research results for: {query}\n"]
    idx = 1
    for site_name, results in all_results.items():
        chat_lines.append(f"### {site_name}")
        if isinstance(results, str):
            chat_lines.append(results)
            chat_lines.append("")
            continue
        for r in results:
            chat_lines.append(f"{idx}. [{r['title']}]({r['url']})")
            if r["snippet"]:
                chat_lines.append(f"   > {r['snippet']}")
            idx += 1
        chat_lines.append("")
    chat_output = "\n".join(chat_lines)

    # TTS output
    if "tts" in formats:
        total = sum(len(v) for v in all_results.values() if isinstance(v, list))
        site_count = len(all_results)
        top_titles = []
        for results in all_results.values():
            if isinstance(results, list):
                for r in results[:2]:
                    if r["title"] != "(no results parsed)":
                        top_titles.append(r["title"])
            if len(top_titles) >= 3:
                break
        top_str = ", ".join(top_titles[:3]) if top_titles else "none"
        tts_msg = (
            f"Found {total} results across {site_count} sites for '{query}'. "
            f"Top results: {top_str}."
        )
        await events.emit("speak", {"message": tts_msg})

    # File output
    if "file" in formats:
        try:
            _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"{_query_slug(query)}_{date.today().isoformat()}.md"
            fpath = _RESEARCH_DIR / fname
            fpath.write_text(_results_to_markdown(query, all_results))
            chat_output += f"\n\nResults saved to `{fpath}`."
        except Exception as exc:
            chat_output += f"\n\n(File output failed: {exc})"

    # Browser output
    if "browser" in formats:
        try:
            import tempfile
            html = _results_to_html(query, all_results)
            slug = _query_slug(query)
            with tempfile.NamedTemporaryFile(
                prefix=f"plia_research_{slug}_", suffix=".html", delete=False
            ) as f:
                f.write(html.encode())
                fpath = f.name
            subprocess.Popen(["xdg-open", fpath])
            chat_output += f"\n\nOpened results in browser (`{fpath}`)."
        except FileNotFoundError:
            chat_output += "\n\n(Browser output unavailable — xdg-open not found.)"
        except Exception as exc:
            chat_output += f"\n\n(Browser output failed: {exc})"

    return chat_output
```

- [ ] **Step 4: Run search tests to verify they pass**

```bash
pytest tests/test_research_tools.py -v
```

Expected: all 18 tests pass (11 from Task 3 + 7 new search tests).

- [ ] **Step 5: Commit**

```bash
git add modules/research_tools.py tests/test_research_tools.py
git commit -m "feat(research): add research_search tool with multi-site fetch and output formats"
```

---

### Task 5: Agent CRUD Tools

**Files:**
- Modify: `modules/agent_tools.py` (append `create_agent`, `edit_agent`, `delete_agent`)
- Create: `tests/test_agent_crud_tools.py`

**Interfaces:**
- Consumes:
  - `core.agent_store.AgentDef` dataclass with fields: `name`, `display_name`, `system_prompt`, `tool_names: list[str]`, `keywords: list[str]`, `llm_description`, `enabled`, `created_at`, `workflow_name`
  - `core.agent_store.save_agent(defn: AgentDef) -> None` — raises `ValueError` for invalid slug
  - `core.agent_store.get_agent(name: str) -> AgentDef | None`
  - `core.agent_store.delete_agent(name: str) -> bool`
  - `core.supervisor._reload_custom_agents() -> None` — must call after every mutation

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_crud_tools.py
import pytest
from unittest.mock import patch, MagicMock


def test_create_agent_success():
    mock_save = MagicMock()
    mock_reload = MagicMock()
    with patch("core.agent_store.get_agent", return_value=None), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import create_agent
        result = create_agent(
            name="mhd-research",
            system_prompt="You search for MHD papers.",
            display_name="MHD Research Agent",
            description="Searches for MHD papers",
            tool_names="research_search,list_research_sites",
            keywords="mhd,saltwater generator",
        )
    assert mock_save.called
    saved = mock_save.call_args[0][0]
    assert saved.name == "mhd-research"
    assert saved.display_name == "MHD Research Agent"
    assert saved.tool_names == ["research_search", "list_research_sites"]
    assert saved.keywords == ["mhd", "saltwater generator"]
    assert mock_reload.called
    assert "created" in result.lower()


def test_create_agent_invalid_slug():
    with patch("core.agent_store.get_agent", return_value=None):
        from modules.agent_tools import create_agent
        result = create_agent(
            name="Bad Name!",
            system_prompt="prompt",
        )
    assert "lowercase" in result.lower() or "invalid" in result.lower()


def test_create_agent_already_exists():
    mock_existing = MagicMock()
    with patch("core.agent_store.get_agent", return_value=mock_existing):
        from modules.agent_tools import create_agent
        result = create_agent(name="my-agent", system_prompt="prompt")
    assert "already exists" in result.lower()
    assert "edit_agent" in result


def test_create_agent_empty_tool_names_stores_empty_list():
    mock_save = MagicMock()
    with patch("core.agent_store.get_agent", return_value=None), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import create_agent
        create_agent(name="bare-agent", system_prompt="prompt", tool_names="")
    saved = mock_save.call_args[0][0]
    assert saved.tool_names == []


def test_edit_agent_updates_fields():
    mock_defn = MagicMock()
    mock_defn.display_name = "Old Name"
    mock_defn.llm_description = "old desc"
    mock_defn.system_prompt = "old prompt"
    mock_defn.tool_names = []
    mock_defn.keywords = []
    mock_save = MagicMock()
    mock_reload = MagicMock()
    with patch("core.agent_store.get_agent", return_value=mock_defn), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import edit_agent
        result = edit_agent(
            name="my-agent",
            display_name="New Name",
            description="new desc",
            tool_names="research_search",
        )
    assert mock_defn.display_name == "New Name"
    assert mock_defn.llm_description == "new desc"
    assert mock_defn.tool_names == ["research_search"]
    assert mock_reload.called
    assert "updated" in result.lower()


def test_edit_agent_not_found():
    with patch("core.agent_store.get_agent", return_value=None):
        from modules.agent_tools import edit_agent
        result = edit_agent(name="no-such-agent", display_name="X")
    assert "no agent" in result.lower() or "not found" in result.lower()


def test_edit_agent_skips_empty_strings():
    mock_defn = MagicMock()
    mock_defn.display_name = "Keep This"
    mock_defn.system_prompt = "Keep This Too"
    mock_defn.tool_names = ["existing-tool"]
    mock_defn.keywords = []
    mock_defn.llm_description = "keep"
    with patch("core.agent_store.get_agent", return_value=mock_defn), \
         patch("core.agent_store.save_agent"), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import edit_agent
        edit_agent(name="my-agent", display_name="", system_prompt="", tool_names="")
    assert mock_defn.display_name == "Keep This"
    assert mock_defn.system_prompt == "Keep This Too"
    assert mock_defn.tool_names == ["existing-tool"]


def test_delete_agent_success():
    mock_reload = MagicMock()
    with patch("core.agent_store.delete_agent", return_value=True) as mock_del, \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import delete_agent
        result = delete_agent("my-agent")
    mock_del.assert_called_once_with("my-agent")
    assert mock_reload.called
    assert "deleted" in result.lower()


def test_delete_agent_not_found():
    with patch("core.agent_store.delete_agent", return_value=False), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import delete_agent
        result = delete_agent("ghost-agent")
    assert "no agent" in result.lower() or "not found" in result.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_agent_crud_tools.py -v
```

Expected: `ImportError` — `create_agent`, `edit_agent`, `delete_agent` not defined in `modules/agent_tools.py`

- [ ] **Step 3: Append CRUD tools to `modules/agent_tools.py`**

Add after the `run_agent` function (end of file):

```python
@tool(
    "Create a new custom agent. "
    "name: slug (lowercase letters, digits, hyphens only — e.g. 'mhd-research'). "
    "system_prompt: the agent's instructions. "
    "display_name: friendly label shown in lists (defaults to name). "
    "description: what this agent does, shown in list_custom_agents. "
    "tool_names: comma-separated tool names the agent may call (e.g. 'research_search,scrape_url'). "
    "keywords: comma-separated phrases that trigger this agent automatically (e.g. 'mhd,saltwater')."
)
def create_agent(
    name: str,
    system_prompt: str,
    display_name: str = "",
    description: str = "",
    tool_names: str = "",
    keywords: str = "",
) -> str:
    import re
    from core.agent_store import AgentDef
    from core.agent_store import save_agent as _save, get_agent as _get
    from core.supervisor import _reload_custom_agents

    if not re.match(r"^[a-z0-9-]+$", name):
        return "Name must be lowercase letters, digits, and hyphens only."
    if _get(name) is not None:
        return f"Agent '{name}' already exists. Use edit_agent to update it."

    tools_list = [t.strip() for t in tool_names.split(",") if t.strip()] if tool_names else []
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []

    defn = AgentDef(
        name=name,
        display_name=display_name or name,
        system_prompt=system_prompt,
        tool_names=tools_list,
        keywords=kw_list,
        llm_description=description,
    )
    try:
        _save(defn)
    except ValueError as exc:
        return str(exc)
    _reload_custom_agents()
    return f"Agent '{name}' created."


@tool(
    "Edit an existing custom agent. Only non-empty fields are updated — omit a field to keep the current value. "
    "name: the agent's slug (cannot be changed). "
    "system_prompt: replace the agent's instructions. "
    "display_name: replace the friendly label. "
    "description: replace the description shown in list_custom_agents. "
    "tool_names: comma-separated — replaces the full list. "
    "keywords: comma-separated — replaces the full list."
)
def edit_agent(
    name: str,
    display_name: str = "",
    description: str = "",
    system_prompt: str = "",
    tool_names: str = "",
    keywords: str = "",
) -> str:
    from core.agent_store import get_agent as _get, save_agent as _save
    from core.supervisor import _reload_custom_agents

    defn = _get(name)
    if defn is None:
        return f"No agent named '{name}'."

    if display_name:
        defn.display_name = display_name
    if description:
        defn.llm_description = description
    if system_prompt:
        defn.system_prompt = system_prompt
    if tool_names:
        defn.tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]
    if keywords:
        defn.keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    _save(defn)
    _reload_custom_agents()
    return f"Agent '{name}' updated."


@tool("Delete a custom agent by its slug name.")
def delete_agent(name: str) -> str:
    from core.agent_store import delete_agent as _delete
    from core.supervisor import _reload_custom_agents

    if not _delete(name):
        return f"No agent named '{name}'."
    _reload_custom_agents()
    return f"Agent '{name}' deleted."
```

- [ ] **Step 4: Run CRUD tests to verify they pass**

```bash
pytest tests/test_agent_crud_tools.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass (1872 + new tests).

- [ ] **Step 6: Commit**

```bash
git add modules/agent_tools.py tests/test_agent_crud_tools.py
git commit -m "feat(agents): add create_agent, edit_agent, delete_agent LLM tools"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Site registry CRUD + 14 predefined sites | Task 1 |
| Env-var overridable file path | Task 1 (`_SITES_FILE`) |
| `credential_backend` config field + constraint | Task 2 |
| Keyring primary storage | Task 2 |
| AES-256 fallback on keyring failure | Task 2 |
| Self-heal: config updated on failure | Task 2 |
| Key derivation: `SHA-256(hostname + user)` | Task 2 |
| `set/get/remove/has_credentials` API | Task 2 |
| `keyring` + `cryptography` deps in `pyproject.toml` | Task 2 |
| `list/add/remove_research_site` tools | Task 3 |
| `set/check/remove_site_credentials` tools | Task 3 |
| `research_search` multi-site fetch | Task 4 |
| Login-required handling — no creds | Task 4 |
| HTTP Basic Auth attempt for stored creds | Task 4 |
| Timeout handling (15s) | Task 4 |
| HTTP error handling (4xx/5xx) | Task 4 |
| Output: chat (markdown) | Task 4 |
| Output: tts (speak event) | Task 4 |
| Output: file (~/research/…md) | Task 4 |
| Output: browser (xdg-open HTML) | Task 4 |
| Numbered results for follow-up scrape | Task 4 |
| `create_agent` + slug validation + duplicate check | Task 5 |
| `edit_agent` + skip-empty fields | Task 5 |
| `delete_agent` | Task 5 |
| `_reload_custom_agents` called after every mutation | Task 5 |
| `tool_names`/`keywords` comma-split + strip | Task 5 |

**Placeholder scan:** None found.

**Type consistency check:**
- `list_sites()` returns `list[dict]` with `slug` key injected — all Task 3/4 consumers iterate `s["slug"]` ✓
- `get_site()` returns `dict | None` with `slug` key — Task 3 checks `is None` ✓
- `set_credentials()` returns `str` — Task 3 passes through to tool result ✓
- `get_credentials()` returns `dict | None` — Task 4 checks before using ✓
- `_reload_custom_agents()` takes no args — all Task 5 calls match ✓
- `save_agent(defn: AgentDef)` — Task 5 constructs `AgentDef` with all required fields ✓
- `delete_agent(name: str) -> bool` from `core.agent_store` — imported as `_delete` to avoid collision with tool function ✓
