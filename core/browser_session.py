from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _sessions_dir() -> Path:
    base = Path(
        os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
    ).parent
    return base / "sessions"


def session_path(slug: str) -> Path:
    return _sessions_dir() / f"{slug}.json"


def has_session(slug: str) -> bool:
    try:
        return session_path(slug).stat().st_size > 0
    except OSError:
        return False


def save_session(slug: str, state: dict) -> None:
    p = session_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state))
    p.chmod(0o600)


def clear_session(slug: str) -> bool:
    try:
        session_path(slug).unlink()
        return True
    except OSError:
        return False


async def _try_scripted_login(page, username: str, password: str) -> bool:
    """Best-effort form fill from stored credentials. Only pre-fills — callers
    ignore the return value and rely on explicit finish_login for completion."""
    try:
        pw = page.locator("input[type=password]")
        if await pw.count() == 0:
            return False
        user = page.locator(
            "input[type=email], input[type=text], input[name*=user i], input[id*=user i]"
        )
        if await user.count() == 0:
            return False
        await user.first.fill(username)
        await pw.first.fill(password)
        await page.locator(
            'button[type=submit], input[type=submit], '
            'button:has-text("Sign in"), button:has-text("Log in")'
        ).first.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return True
    except Exception:
        return False


_ACTIVE_LOGINS: dict[str, dict] = {}


def _import_async_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except Exception:
        return None


async def _safe_close(browser=None, pw=None) -> None:
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if pw is not None:
        try:
            await pw.stop()
        except Exception:
            pass


async def _close_active(slug: str) -> None:
    entry = _ACTIVE_LOGINS.pop(slug, None)
    if not entry:
        return
    await _safe_close(entry.get("browser"), entry.get("pw"))


async def start_login(slug: str, url: str, username: str, password: str) -> str:
    ap = _import_async_playwright()
    if ap is None:
        return "Playwright not installed. Run: pip install -e '.[playwright]' && playwright install chromium"
    await _close_active(slug)
    try:
        pw = await ap().start()
    except Exception as exc:
        logger.warning("Playwright start failed: %s", exc)
        return "Could not start the browser engine. Run: playwright install chromium"
    try:
        browser = await pw.chromium.launch(headless=False)
    except Exception as exc:
        logger.warning("Headed browser launch failed: %s", exc)
        await _safe_close(pw=pw)
        return "Could not open a browser (no display?). Run Plia on a machine with a display to sign in."
    try:
        context = await browser.new_context()
        page = await context.new_page()
    except Exception as exc:
        logger.warning("Could not create a browser page for %s: %s", slug, exc)
        await _safe_close(browser, pw)
        return f"Could not open a browser page for '{slug}'."
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await _try_scripted_login(page, username, password)
    except Exception as exc:
        # Non-fatal: leave the browser open so the user can navigate/sign in by hand.
        logger.warning("Login page load/prefill error for %s: %s", slug, exc)
    _ACTIVE_LOGINS[slug] = {"pw": pw, "browser": browser, "context": context}
    return f"Opened a browser for '{slug}'. Finish signing in, then run finish_login('{slug}')."


async def finish_login(slug: str) -> str:
    entry = _ACTIVE_LOGINS.pop(slug, None)
    if entry is None:
        return f"No login in progress for '{slug}'. Run login_site('{slug}') first."
    saved, err = True, ""
    try:
        state = await entry["context"].storage_state()
        save_session(slug, state)
    except Exception as exc:
        saved, err = False, str(exc)
        logger.warning("finish_login save failed for %s: %s", slug, exc)
    finally:
        await _safe_close(entry["browser"], entry["pw"])
    if not saved:
        return f"Could not save the session for '{slug}': {err}"
    return f"Saved the session for '{slug}'."


async def authed_fetch(slug: str, url: str) -> tuple[str | None, bool]:
    """Fetch url through the saved session, returning rendered HTML. Returns
    (None, False) with no session, no Playwright, a login bounce, or any error."""
    if not has_session(slug):
        return None, False
    ap = _import_async_playwright()
    if ap is None:
        return None, False
    pw = await ap().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=str(session_path(slug)))
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if await page.locator("input[type=password]").count() > 0:
                return None, False
            return await page.content(), True
        finally:
            await browser.close()
    except Exception as exc:
        logger.warning("authed_fetch error for %s: %s", slug, exc)
        return None, False
    finally:
        try:
            await pw.stop()
        except Exception:
            pass
