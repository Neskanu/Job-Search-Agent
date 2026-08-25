"""
src/browser_manager.py - Persistent Browser Context & Session Manager

Provides unified Playwright Chromium context management with lock-cleaning routines,
stealth initialization, and LinkedIn session cookie handling.
"""

import os
import time
import sys
import threading
from queue import Queue
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page


def cleanup_profile_locks(user_data_dir: str) -> None:
    """Safely remove stale Chromium profile lock files on Windows/Linux."""
    if not os.path.exists(user_data_dir):
        return
        
    lock_names = {
        "lockfile", "lock", "singletonlock", "singletoncookie",
        "singletonsocket", "devtoolsactiveport", "parent.lock"
    }
    
    for root, _, files in os.walk(user_data_dir):
        for f in files:
            if f.lower() in lock_names or "lock" in f.lower():
                try:
                    os.remove(os.path.join(root, f))
                except Exception as e:
                    print(f"[browser_manager] Failed to remove lock file {os.path.join(root, f)}: {e}")
                    pass


STORAGE_STATE_PATH = os.path.abspath(os.path.join("data", "storage_state.json"))


def prepare_linkedin_cookies(li_at_value: str) -> List[Dict[str, Any]]:
    """Convert raw li_at cookie string to Playwright cookie format across LinkedIn domains."""
    if not li_at_value:
        return []
    cleaned_val = li_at_value.strip().strip('"').strip("'")
    if not cleaned_val or cleaned_val.lower() in ["none", "null", "undefined"]:
        return []

    exp = time.time() + 3600 * 24 * 30  # 30 days
    return [
        {
            "name": "li_at",
            "value": cleaned_val,
            "domain": ".linkedin.com",
            "path": "/",
            "expires": exp,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        },
        {
            "name": "li_at",
            "value": cleaned_val,
            "domain": "www.linkedin.com",
            "path": "/",
            "expires": exp,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        }
    ]


def ensure_linkedin_session(context: BrowserContext, li_at: str, logger_fn=print) -> bool:
    """
    Perform initial LinkedIn session handshake on https://www.linkedin.com/feed to establish full cookies
    and save storage_state.json. If handshake fails or hits a redirect loop due to invalid cookies,
    clears cookies so job URL navigation can proceed cleanly.
    """
    # Log current LinkedIn cookie metadata cleanly
    try:
        cookies = context.cookies("https://www.linkedin.com")
        for cookie in cookies:
            logger_fn(f"LinkedIn cookie metadata: name={cookie.get('name')}, domain={cookie.get('domain')}, path={cookie.get('path')}")
    except Exception as e:
        logger_fn(f"[browser_manager] Note reading cookies during handshake: {e}")
        pass

    if os.path.exists(STORAGE_STATE_PATH) and os.path.getsize(STORAGE_STATE_PATH) > 50:
        logger_fn("Restored existing LinkedIn session state from storage_state.json.")
        return True

    has_cookie = bool(li_at and li_at.lower() not in ("none", "null", "undefined"))
    if has_cookie:
        try:
            context.add_cookies(prepare_linkedin_cookies(li_at))
            logger_fn("Injected session cookie (li_at).")
        except Exception as e:
            logger_fn(f"Warning adding cookies: {e}")
    else:
        logger_fn("No li_at session cookie provided. Proceeding with clean browser context.")
        return False

    page = context.new_page()
    try:
        logger_fn("Performing initial LinkedIn session handshake on https://www.linkedin.com/feed ...")
        page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=15000)
        time.sleep(1.5)
        curr_url = page.url.lower()
        if any(k in curr_url for k in ["linkedin.com/feed", "linkedin.com/in/", "linkedin.com/mynetwork"]):
            logger_fn("LinkedIn session handshake successful!")
            try:
                os.makedirs(os.path.dirname(STORAGE_STATE_PATH), exist_ok=True)
                context.storage_state(path=STORAGE_STATE_PATH)
                logger_fn("Saved LinkedIn storage state to storage_state.json.")
            except Exception as e:
                logger_fn(f"[browser_manager] Failed to save storage_state.json: {e}")
                pass
            return True
        else:
            logger_fn(f"Session handshake landed on: {page.url}")
            return False
    except Exception as err:
        logger_fn(f"Session handshake note: {err}")
        # If injected cookie caused redirect loop, clear cookies to prevent blocking job URL navigation
        try:
            context.clear_cookies()
            logger_fn("Cleared invalid session cookies to prevent redirect loop.")
        except Exception as e:
            logger_fn(f"[browser_manager] Failed to clear cookies: {e}")
            pass
        return False
    finally:
        try:
            page.close()
        except Exception as e:
            logger_fn(f"[browser_manager] Failed to close handshake page: {e}")
            pass


def create_browser_context(
    pw,
    user_data_dir: Optional[str] = os.path.join("data", "browser_profile"),
    use_persistent: bool = True
) -> BrowserContext:
    """
    Launch Chromium browser context with stealth parameters.
    Uses storage_state.json if available to load saved authenticated sessions without redirect loops.
    """
    stealth_args = [
        "--start-maximized",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

    storage_state = STORAGE_STATE_PATH if (os.path.exists(STORAGE_STATE_PATH) and os.path.getsize(STORAGE_STATE_PATH) > 50) else None

    if storage_state:
        print("[browser_manager] Launching clean Chromium context with saved storage_state.json...")
        browser = pw.chromium.launch(headless=False, args=stealth_args)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=ua, storage_state=storage_state)
        _apply_stealth_scripts(ctx)
        return ctx

    # Standard clean browser context launch (same pattern as scraper.py)
    print("[browser_manager] Launching clean Chromium browser context...")
    browser = pw.chromium.launch(headless=False, args=stealth_args)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=ua)
    _apply_stealth_scripts(ctx)
    return ctx


def _apply_stealth_scripts(ctx: BrowserContext) -> None:
    """Inject stealth scripts into browser context to mask automation flags."""
    try:
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)
    except Exception as e:
        print(f"[browser_manager] Failed to apply stealth scripts: {e}")
        pass


def run_in_proactor_thread(func, *args, **kwargs):
    """
    Run a Playwright function in a new thread with Windows ProactorEventLoopPolicy.
    """
    q = Queue()

    def wrapper():
        if sys.platform == 'win32':
            import asyncio
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception as e:
                print(f"[browser_manager] Could not set WindowsProactorEventLoopPolicy: {e}")
                pass
        try:
            res = func(*args, **kwargs)
            q.put((True, res))
        except Exception as e:
            import traceback
            q.put((False, (e, traceback.format_exc())))

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    t.join()

    success, val = q.get()
    if success:
        return val
    else:
        exc, tb = val
        raise RuntimeError(f"Error in browser thread: {exc}\n{tb}")
