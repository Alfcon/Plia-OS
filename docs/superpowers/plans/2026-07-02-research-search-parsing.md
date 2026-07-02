# Research Search Result Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `research_search` return real search results (not navigation chrome) for static-HTML sites.

**Architecture:** Rewrite the generic link extractor in `modules/research_tools.py` to absolutize relative URLs, strip nav/boilerplate, and dedupe (Task 1). Add a tiny per-site parser registry seeded with an arXiv parser and wire it into the per-site fetch path (Task 2).

**Tech Stack:** Python 3.12, stdlib `re` + `urllib.parse`, pytest.

## Global Constraints

- No new pip dependencies.
- `_extract_snippets` returns the existing shape: `list[{"title": str, "url": str, "snippet": str}]`.
- Anchor-text length floor is 15 chars; boilerplate denylist is **phrase-level only** (no bare words like `home`/`about`/`menu`).
- Parser functions are pure and defensive — a structural mismatch returns `[]`, never raises.
- The `"(no results parsed)"` fallback entry stays when a site yields no snippets.
- Run tests with: `source .venv/bin/activate && pytest tests/test_research_tools.py -v`
- Full suite: `source .venv/bin/activate && pytest --tb=short -q`

---

### Task 1: Rewrite the generic extractor

**Files:**
- Modify: `modules/research_tools.py` (replace `_extract_snippets`, update its one call site, add `_BOILERPLATE_PHRASES`)
- Modify: `tests/test_research_tools.py` (add unit tests; lengthen three short fixture titles)

**Interfaces:**
- Produces: `_extract_snippets(html: str, base_url: str, max_results: int = 10) -> list[dict]` — new required `base_url` param used to absolutize relative hrefs.
- Consumes: `_search_one` (existing) now calls `_extract_snippets(resp.text, url)`.

- [ ] **Step 1: Write the failing generic-extractor tests**

Add to `tests/test_research_tools.py` (top-level, after the imports):

```python
def test_extract_snippets_absolutizes_relative_urls():
    from modules.research_tools import _extract_snippets
    html = '<a href="/abs/2301.001">Quantum Turbulence in Superfluids</a> abstract text here'
    out = _extract_snippets(html, "https://arxiv.org/search/?q=x")
    assert out[0]["url"] == "https://arxiv.org/abs/2301.001"
    assert out[0]["title"] == "Quantum Turbulence in Superfluids"


def test_extract_snippets_filters_nav_and_boilerplate():
    from modules.research_tools import _extract_snippets
    html = (
        '<nav><a href="/home">Home</a></nav>'
        '<a href="https://x.org/login">Log in to your account</a>'
        '<a href="/donate">Donate</a>'
        '<a href="/paper/1">Magnetohydrodynamic Saltwater Generators</a> some context'
    )
    out = _extract_snippets(html, "https://x.org/search")
    assert [r["title"] for r in out] == ["Magnetohydrodynamic Saltwater Generators"]


def test_extract_snippets_dedupes_and_drops_self_link():
    from modules.research_tools import _extract_snippets
    html = (
        '<a href="https://x.org/search">the search page itself here</a>'
        '<a href="/p/1">A Genuine Result Title One</a> a'
        '<a href="/p/1">A Genuine Result Title One</a> b'
    )
    out = _extract_snippets(html, "https://x.org/search")
    assert len(out) == 1
    assert out[0]["url"] == "https://x.org/p/1"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_research_tools.py -k extract_snippets -v
```
Expected: FAIL — `_extract_snippets()` currently takes no `base_url` (TypeError) / relative URLs not absolutized.

- [ ] **Step 3: Replace `_extract_snippets`**

In `modules/research_tools.py`, replace the whole existing function:

```python
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
```

with:

```python
_BOILERPLATE_PHRASES = (
    "skip to", "sign in", "sign up", "log in", "learn more", "advanced search",
    "privacy policy", "cookie policy", "terms of service", "terms of use",
    "create account", "forgot password", "subscribe to", "newsletter",
)


def _extract_snippets(html: str, base_url: str, max_results: int = 10) -> list[dict]:
    from urllib.parse import urljoin
    html = _re.sub(
        r"<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>",
        "", html, flags=_re.DOTALL | _re.IGNORECASE,
    )
    pattern = _re.compile(
        r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        _re.DOTALL | _re.IGNORECASE,
    )
    results: list[dict] = []
    seen: set[str] = set()
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        if url == base_url or url in seen:
            continue
        text = _re.sub(r"<[^>]+>", "", m.group(2))
        text = _re.sub(r"\s+", " ", text).strip()
        if len(text) < 15 or len(text) > 300:
            continue
        low = text.lower()
        if any(p in low for p in _BOILERPLATE_PHRASES):
            continue
        raw_after = html[m.end():m.end() + 600]
        snippet = _re.sub(r"<[^>]+>", " ", raw_after)
        snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": text, "url": url, "snippet": snippet})
        seen.add(url)
        if len(results) >= max_results:
            break
    return results
```

- [ ] **Step 4: Update the call site**

In `modules/research_tools.py`, inside `_search_one`, find:

```python
        snippets = _extract_snippets(resp.text)
```
Replace with:
```python
        snippets = _extract_snippets(resp.text, url)
```

- [ ] **Step 5: Lengthen three short fixture titles**

The new 15-char floor filters titles under 15 chars. Three existing `research_search`
tests use short titles. In `tests/test_research_tools.py` make these exact replacements:

- `>Title One</a>` → `>Title One Paper Result</a>`
- `>Paper Title</a>` → `>Paper Title Extended</a>`
- `>Browser Title</a>` → `>Browser Title Result</a>`

(The `file_output` test asserts `"Paper Title" in ...`, which is still a substring of
`"Paper Title Extended"`, so it stays green.)

- [ ] **Step 6: Run the new unit tests and the full research suite**

```bash
source .venv/bin/activate && pytest tests/test_research_tools.py -v
```
Expected: PASS — new `extract_snippets` tests pass and all pre-existing `research_search` tests stay green.

- [ ] **Step 7: Commit**

```bash
git add modules/research_tools.py tests/test_research_tools.py
git commit -m "feat(research): rewrite generic result extractor — absolutize URLs, strip nav/boilerplate, dedupe"
```

---

### Task 2: arXiv per-site parser + registry wiring

**Files:**
- Modify: `modules/research_tools.py` (add `_parse_arxiv`, `_SITE_PARSERS`, parser lookup in `_search_one`)
- Modify: `tests/test_research_tools.py` (add arXiv parser unit tests + one integration test)

**Interfaces:**
- Consumes: `_extract_snippets(html, base_url)` (Task 1); `research_search`, `_search_one`, `_fetch` (existing).
- Produces: `_parse_arxiv(html: str, base_url: str) -> list[dict]`; `_SITE_PARSERS: dict[str, callable]` mapping slug → parser.

- [ ] **Step 1: Write the failing arXiv tests**

Add to `tests/test_research_tools.py`:

```python
def test_parse_arxiv_extracts_results():
    from modules.research_tools import _parse_arxiv
    html = (
        '<li class="arxiv-result">'
        '<p class="list-title is-inline-block"><a href="/abs/2301.00001">arXiv:2301.00001</a></p>'
        '<p class="title is-5 mathjax">Magnetohydrodynamic Power from Seawater</p>'
        '<span class="abstract-full">We study MHD generators driven by saltwater flow.</span>'
        '</li>'
    )
    out = _parse_arxiv(html, "https://arxiv.org/search/?q=mhd")
    assert len(out) == 1
    assert out[0]["title"] == "Magnetohydrodynamic Power from Seawater"
    assert out[0]["url"] == "https://arxiv.org/abs/2301.00001"
    assert "saltwater" in out[0]["snippet"]


def test_parse_arxiv_malformed_returns_empty():
    from modules.research_tools import _parse_arxiv
    assert _parse_arxiv("<html>no results here</html>", "https://arxiv.org/") == []


@pytest.mark.asyncio
async def test_research_search_uses_arxiv_parser():
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    html = (
        '<li class="arxiv-result">'
        '<p class="list-title"><a href="/abs/9.9">arXiv:9.9</a></p>'
        '<p class="title is-5 mathjax">Deep Result From Arxiv Parser</p>'
        '<span class="abstract-full">body text</span>'
        '</li>'
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("q", sites="arxiv", output_formats="chat")

    assert "Deep Result From Arxiv Parser" in result
    assert "arxiv.org/abs/9.9" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_research_tools.py -k "arxiv" -v
```
Expected: FAIL — `_parse_arxiv` does not exist; integration test still uses the generic path.

- [ ] **Step 3: Add `_parse_arxiv` and the registry**

In `modules/research_tools.py`, immediately after `_extract_snippets`, add:

```python
def _parse_arxiv(html: str, base_url: str) -> list[dict]:
    from urllib.parse import urljoin
    results: list[dict] = []
    for block in _re.findall(r'<li class="arxiv-result">(.*?)</li>', html, _re.DOTALL | _re.IGNORECASE):
        m_url = _re.search(r'<a href="([^"]*?/abs/[^"]*)"', block, _re.IGNORECASE)
        m_title = _re.search(r'<p class="title[^"]*">(.*?)</p>', block, _re.DOTALL | _re.IGNORECASE)
        if not m_url or not m_title:
            continue
        title = _re.sub(r"<[^>]+>", "", m_title.group(1))
        title = _re.sub(r"\s+", " ", title).strip()
        snippet = ""
        m_abs = _re.search(r'<span class="abstract-full[^"]*">(.*?)</span>', block, _re.DOTALL | _re.IGNORECASE)
        if m_abs:
            snippet = _re.sub(r"<[^>]+>", " ", m_abs.group(1))
            snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": title, "url": urljoin(base_url, m_url.group(1)), "snippet": snippet})
    return results


_SITE_PARSERS = {
    "arxiv": _parse_arxiv,
}
```

- [ ] **Step 4: Wire the registry into `_search_one`**

In `_search_one`, find (as left by Task 1):

```python
        snippets = _extract_snippets(resp.text, url)
        return site_name, (snippets if snippets else [{"title": "(no results parsed)", "url": url, "snippet": ""}])
```
Replace with:
```python
        parser = _SITE_PARSERS.get(slug)
        snippets = parser(resp.text, url) if parser else _extract_snippets(resp.text, url)
        return site_name, (snippets if snippets else [{"title": "(no results parsed)", "url": url, "snippet": ""}])
```

- [ ] **Step 5: Run the arXiv tests, then the full research suite**

```bash
source .venv/bin/activate && pytest tests/test_research_tools.py -v
```
Expected: PASS — arXiv unit + integration tests pass, everything else stays green.

- [ ] **Step 6: Run the full suite for regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add modules/research_tools.py tests/test_research_tools.py
git commit -m "feat(research): add arXiv per-site parser and site-parser registry"
```
