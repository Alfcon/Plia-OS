# Research Search Result Parsing — Design

**Date:** 2026-07-02
**Status:** Approved, ready for implementation plan

## Problem

`research_search` (in `modules/research_tools.py`) fetches each site's search page
and extracts result links via `_extract_snippets`. Run live against arXiv, it
returns navigation chrome ("Donate", "Log in", "Submit", "Learn more") instead of
paper listings.

Root cause: `_extract_snippets` requires `href.startswith("http")`, so it keeps
only *absolute* nav links and discards the actual result titles, which on many
sites (arXiv especially) are *relative* links like `/abs/2301.00001`. The
extractor also does no boilerplate filtering, so any absolute link with 5–300
chars of text is treated as a result.

## Goal

Make `research_search` return real search results for static-HTML sites, without
taking on the JS/login-site problem (deferred to Phase 2 / Playwright).

## Approach

Hybrid, kept minimal: a much stronger **generic** extractor that fixes the 80%
case for all sites, plus a small **per-site parser registry** seeded with one
concrete parser (arXiv) as the precision case and the extension point for later.

Rationale: absolutizing relative URLs alone flips arXiv from all-nav to
mostly-papers; the boilerplate filter removes the rest of the chrome. Per-site
parsers are YAGNI for the other 13 sites until generic is proven insufficient
for a specific one.

## Components

### 1. `_extract_snippets(html, base_url, max_results=10) -> list[dict]`

Rewritten generic extractor. New signature adds `base_url` (the resolved search
URL) so relative links can be absolutized. Returns the same
`[{"title", "url", "snippet"}]` shape as today.

Steps:
- Strip `script`, `style`, `nav`, `header`, `footer`, `aside`, `form` blocks
  (currently only `script`/`style`).
- For each `<a href=…>`: absolutize with `urllib.parse.urljoin(base_url, href)`.
- Reject an anchor when any of:
  - href is empty, a fragment (`#…`), `mailto:`, `tel:`, or `javascript:`;
  - the absolutized URL equals `base_url` (self/search link);
  - anchor text length < 15 or > 300 (after tag-stripping and whitespace
    collapse) — this floor already removes short nav labels ("Home", "About",
    "Log in", "Submit", "Menu", "Help", "Donate"), so the denylist need not;
  - anchor text matches the boilerplate denylist (case-insensitive substring).
    The denylist is **phrase-level only** — no bare common words like `home`,
    `about`, `menu`, `terms` (those are substrings of real titles such as
    "Home range dynamics…" and would cause false negatives; the length floor
    handles the short nav versions). Denylist: `skip to`, `sign in`, `sign up`,
    `log in`, `learn more`, `advanced search`, `privacy policy`, `cookie policy`,
    `terms of service`, `terms of use`, `create account`, `forgot password`,
    `subscribe to`, `newsletter`.
- Dedupe by absolutized URL (first occurrence wins).
- Snippet: text of the block following the anchor, tag-stripped, whitespace
  collapsed, truncated to 200 chars (as today).
- Stop at `max_results`.

### 2. Per-site parser registry

```python
_SITE_PARSERS: dict[str, Callable[[str, str], list[dict]]] = {
    "arxiv": _parse_arxiv,
}
```

`_parse_arxiv(html, base_url)` parses arXiv's stable results markup:
each result is an `<li class="arxiv-result">`; title from
`<p class="title is-5 mathjax">`, URL from the `<a>` whose href contains
`/abs/`, snippet from `<span class="abstract-full">` or the authors line if
present. Falls back to `[]` if the structure isn't found (caller then does not
substitute generic — an empty arXiv parse means "no results parsed", consistent
with current behavior).

### 3. `research_search` wiring

In the per-site fetch coroutine (`_search_one`), after a 200 response:
```python
parser = _SITE_PARSERS.get(slug)
if parser:
    snippets = parser(resp.text, url)
else:
    snippets = _extract_snippets(resp.text, url)
```
`url` is the already-resolved search URL, used as `base_url`. The
"(no results parsed)" fallback entry is kept when `snippets` is empty.

## Data flow

`research_search(query, sites, formats)`
→ per slug: build search `url` → `_fetch(url)` → 200 →
`_SITE_PARSERS[slug]` or `_extract_snippets(html, url)` →
`list[{title,url,snippet}]` → existing chat/tts/file/browser formatting
(unchanged).

## Error handling

Unchanged. Parser functions are pure and defensive: any structural mismatch
yields `[]`, never raises. Network/HTTP/timeout handling in `_search_one` is
untouched.

## Testing

Unit tests with in-repo fixture HTML, `_fetch` patched (no live network):
- Generic: a page mixing nav chrome (absolute nav links, short/boilerplate text)
  with real result links (relative `/x` and absolute) →
  asserts nav filtered, real titles returned, relative URLs absolutized,
  duplicates collapsed, `base_url` self-link dropped.
- arXiv parser: a trimmed `arxiv-result` fixture → asserts titles/URLs/snippets
  parsed and `/abs/` links absolutized; malformed input → `[]`.
- Regression: existing `research_search` tests keep passing (their fixture
  `<a href="https://…">Title</a>` still yields a result under the new rules —
  verify the ≥15-char titles used in tests aren't filtered; adjust fixtures if a
  title is under the length floor).

## Out of scope

- JS-rendered / login-required sites (Google Scholar, ScienceDirect, JSTOR,
  IEEE, Academia.edu) — need Phase 2 Playwright; generic returns whatever static
  HTML provides.
- Result ranking, cross-site dedupe, pagination.
- API-based fetching (NCBI eutils, LoC JSON) — possible future per-site upgrade,
  not now.
