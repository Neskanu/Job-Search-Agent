"""
src/guided_applier.py - Semi-Automated External Portal Application Module

Handles non-Easy-Apply external company job application portals (e.g. Workday, Lever,
Greenhouse, generic company ATS forms).

Key Features:
- Fuzzy matching against persistent memory (data/answers_memory.json)
- Heuristics fallback from structured CV data
- Auto-account creation for Workday (generates secure password, saves to memory)
- Floating status overlay injected into live Chromium page
- Pauses on unrecognized fields & CAPTCHAs, generating screenshots with red-highlighted
  bounding boxes around problematic fields
- Session state persistence (data/portal_sessions/) allowing pause/resume across runs
"""

import os
import re
import time
import json
import random
import secrets
import string
import base64
import difflib
import threading
from datetime import datetime
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, Page, Browser
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Global Session Memory & Active Session Registry
# ---------------------------------------------------------------------------

MEMORY_FILE_PATH = os.path.join("data", "answers_memory.json")
SESSIONS_DIR = os.path.join("data", "portal_sessions")

# Active runtime session store for API status polling
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
ACTIVE_SESSIONS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Answers Memory & Fuzzy Matching Utilities
# ---------------------------------------------------------------------------

def normalize_label(label: str) -> str:
    """
    Normalize field label for fuzzy matching:
    removes punctuation/special chars, collapses extra spaces, lowercases.
    e.g. 'Years of Experience with Python?' -> 'years of experience with python'
    """
    if not label:
        return ""
    cleaned = re.sub(r'[^a-z0-9 ]', ' ', label.lower())
    return re.sub(r'\s+', ' ', cleaned).strip()


def load_answers_memory(path: str = MEMORY_FILE_PATH) -> Dict[str, str]:
    """Load answers memory dictionary from disk. Creates default file if missing."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        default_memory = {
            "first name": "",
            "last name": "",
            "email address": "",
            "phone number": "",
            "linkedin profile url": "",
            "are you legally authorized to work": "Yes",
            "do you require visa sponsorship": "No",
            "salary expectations": "Negotiable",
            "city": "",
            "country": "",
            "linkedin_li_at_cookie": ""
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[guided_applier] Warning initializing memory file: {e}")
        return default_memory

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[guided_applier] Error reading memory file {path}: {e}")
        return {}


def save_answers_memory(memory: Dict[str, str], path: str = MEMORY_FILE_PATH) -> None:
    """Save answers memory dictionary to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[guided_applier] Error saving memory file {path}: {e}")


def fuzzy_lookup(label: str, memory: Dict[str, str], threshold: float = 0.75) -> Tuple[Optional[str], float]:
    """
    Find best matching answer in memory using a combination of difflib SequenceMatcher
    and token set similarity on normalized label strings.
    Returns (answer, match_score) or (None, best_score).
    """
    norm_target = normalize_label(label)
    if not norm_target or not memory:
        return None, 0.0

    target_tokens = set(norm_target.split())
    best_score = 0.0
    best_value = None

    for raw_key, value in memory.items():
        if not value:
            continue
        norm_key = normalize_label(raw_key)
        if not norm_key:
            continue

        # Direct string equality check
        if norm_target == norm_key:
            return value, 1.0

        # 1. Sequence ratio
        seq_score = difflib.SequenceMatcher(None, norm_target, norm_key).ratio()

        # 2. Token overlap ratio (handles word reordering e.g. "Years of Python experience" vs "years of experience with python")
        key_tokens = set(norm_key.split())
        common_tokens = target_tokens & key_tokens
        token_score = (2.0 * len(common_tokens)) / (len(target_tokens) + len(key_tokens)) if (target_tokens and key_tokens) else 0.0

        # Pick best score between sequence and token overlap
        score = max(seq_score, token_score)

        if score > best_score:
            best_score = score
            best_value = value

    if best_score >= threshold:
        return best_value, best_score
    return None, best_score


def generate_secure_password(length: int = 14) -> str:
    """Generate a strong random password for auto-creating portal accounts."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least one upper, lower, digit, special
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*")
    ]
    password += [secrets.choice(alphabet) for _ in range(length - 4)]
    random.shuffle(password)
    return "".join(password)


# ---------------------------------------------------------------------------
# Page Overlay & Visual Highlighting Helpers
# ---------------------------------------------------------------------------

def inject_overlay(page: Page, message: str, step: int = 1, total_steps: int = 1) -> None:
    """Inject floating overlay control panel into live Chromium page DOM."""
    js_code = f"""
    (() => {{
        let overlay = document.getElementById('__agy_overlay__');
        if (!overlay) {{
            overlay = document.createElement('div');
            overlay.id = '__agy_overlay__';
            overlay.style.cssText = `
                position: fixed;
                top: 16px;
                right: 16px;
                z-index: 9999999;
                background: rgba(15, 23, 42, 0.92);
                backdrop-filter: blur(8px);
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 14px 18px;
                color: #F8FAFC;
                font-family: system-ui, -apple-system, sans-serif;
                font-size: 12px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
                max-width: 340px;
                pointer-events: auto;
            `;
            document.body.appendChild(overlay);
        }}
        overlay.innerHTML = `
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; border-bottom:1px solid #334155; padding-bottom:6px;">
                <span style="font-weight:700; color:#FB7185;">🤖 CV Agent Assistant</span>
                <span style="font-size:10px; background:#475569; padding:2px 6px; border-radius:4px;">Step ${{step}}/${{total_steps}}</span>
            </div>
            <div id="__agy_msg__" style="color:#CBD5E1; line-height:1.4; margin-bottom:8px;">${{message}}</div>
            <div style="font-size:10px; color:#94A3B8; italic">Listening for instructions from main app console...</div>
        `;
    }})();
    """
    try:
        page.evaluate(js_code)
    except Exception as e:
        print(f"[guided_applier] Warning injecting overlay: {e}")


def update_overlay_message(page: Page, message: str, step: int = 1, total_steps: int = 1) -> None:
    """Update message in existing page overlay."""
    inject_overlay(page, message, step, total_steps)


def highlight_element_and_screenshot(page: Page, selector_or_element, audit_dir: str, filename_base: str) -> Tuple[str, str]:
    """
    Take screenshot of current page, draw a red 4px rectangle around element's bounding box using PIL,
    and save image. Returns (file_path, base64_data_url).
    """
    os.makedirs(audit_dir, exist_ok=True)
    raw_path = os.path.join(audit_dir, f"{filename_base}_raw.png")
    out_path = os.path.join(audit_dir, f"{filename_base}.png")

    page.screenshot(path=raw_path, full_page=False)

    box = None
    try:
        if isinstance(selector_or_element, str):
            el = page.query_selector(selector_or_element)
            if el:
                box = el.bounding_box()
        elif hasattr(selector_or_element, "bounding_box"):
            box = selector_or_element.bounding_box()
    except Exception as err:
        print(f"[guided_applier] Could not get bounding box for highlight: {err}")

    # Process image with PIL
    try:
        img = Image.open(raw_path).convert("RGBA")
        if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
            draw = ImageDraw.Draw(img)
            x0 = box["x"]
            y0 = box["y"]
            x1 = x0 + box["width"]
            y1 = y0 + box["height"]

            # Draw 4px red highlight border
            for offset in range(4):
                draw.rectangle([x0 - offset, y0 - offset, x1 + offset, y1 + offset], outline=(244, 63, 94, 255)) # Rose red

        img.save(out_path, format="PNG")
        if os.path.exists(raw_path):
            os.remove(raw_path)
    except Exception as e:
        print(f"[guided_applier] Error drawing highlight box: {e}")
        out_path = raw_path

    # Convert out_path to base64
    with open(out_path, "rb") as f:
        b64 = "data:image/png;base64," + base64.b64encode(f.read()).decode()

    return out_path, b64


# ---------------------------------------------------------------------------
# Session Persistence Utilities
# ---------------------------------------------------------------------------

def save_session(
    company: str,
    portal_url: str,
    current_step: int,
    total_steps: int,
    filled_fields: Dict[str, Any],
    status: str,
    paused_field: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None
) -> str:
    """Save application state to data/portal_sessions/<session_id>.json."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    if not session_id:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_comp = re.sub(r'[^a-zA-Z0-9_]', '_', company)
        session_id = f"{safe_comp}_{ts}"

    session_file = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    data = {
        "session_id": session_id,
        "company": company,
        "portal_url": portal_url,
        "current_step": current_step,
        "total_steps": total_steps,
        "filled_fields": filled_fields,
        "status": status,
        "paused_field": paused_field,
        "last_updated": datetime.now().isoformat()
    }

    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[guided_applier] Error writing session file: {e}")

    return session_id


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Load session state from data/portal_sessions/<session_id>.json."""
    session_file = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(session_file):
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[guided_applier] Error loading session file: {e}")
        return None


# ---------------------------------------------------------------------------
# Workday Specific Auth & Account Creation Handler
# ---------------------------------------------------------------------------

def detect_ats_platform(url: str) -> str:
    """Identify if target URL belongs to a known ATS platform."""
    url_lower = url.lower()
    if "workday.com" in url_lower or "myworkdayjobs.com" in url_lower:
        return "workday"
    if "lever.co" in url_lower:
        return "lever"
    if "greenhouse.io" in url_lower:
        return "greenhouse"
    if "icims.com" in url_lower:
        return "icims"
    if "taleo.net" in url_lower:
        return "taleo"
    return "generic"


def handle_workday_auth(page: Page, cv_data: Dict[str, Any], memory: Dict[str, str]) -> bool:
    """
    Handle Workday portal login / account creation if present.
    Creates account using candidate email + generated password if 'Create Account' is detected.
    Returns True if an auth action was executed.
    """
    # Look for Workday Create Account button/link
    create_acct_btn = page.query_selector(
        "[data-automation-id='createAccountButton'], "
        "button:has-text('Create Account'), "
        "a:has-text('Create Account')"
    )

    if create_acct_btn and create_acct_btn.is_visible():
        print("[guided_applier] Workday 'Create Account' button detected. Executing auto-registration...")
        create_acct_btn.click()
        time.sleep(2.0)

        # Get or generate Workday password
        email = memory.get("email address") or cv_data.get("name", "").replace(" ", ".").lower() + "@example.com"
        pwd = memory.get("workday_password") or generate_secure_password()
        memory["workday_password"] = pwd
        save_answers_memory(memory)

        # Fill registration inputs
        email_input = page.query_selector("[data-automation-id='email'], input[type='email']")
        pwd_input = page.query_selector("[data-automation-id='password'], input[type='password']")
        verify_pwd_input = page.query_selector("[data-automation-id='confirmPassword']")

        if email_input:
            email_input.fill(email)
            time.sleep(0.5)
        if pwd_input:
            pwd_input.fill(pwd)
            time.sleep(0.5)
        if verify_pwd_input:
            verify_pwd_input.fill(pwd)
            time.sleep(0.5)

        # Accept terms checkbox if present
        terms_checkbox = page.query_selector("[data-automation-id='createAccountCheckbox'], input[type='checkbox']")
        if terms_checkbox and not terms_checkbox.is_checked():
            terms_checkbox.click()
            time.sleep(0.5)

        # Click Create Account Submit
        submit_reg = page.query_selector("[data-automation-id='createAccountSubmitButton'], button:has-text('Create Account')")
        if submit_reg:
            submit_reg.click()
            time.sleep(3.0)
            print("[guided_applier] Workday account created successfully.")
            return True

    # Check for Sign In
    signin_btn = page.query_selector("[data-automation-id='signInSubmitButton']")
    if signin_btn and signin_btn.is_visible():
        email = memory.get("email address") or ""
        pwd = memory.get("workday_password") or ""
        if email and pwd:
            email_input = page.query_selector("[data-automation-id='email']")
            pwd_input = page.query_selector("[data-automation-id='password']")
            if email_input: email_input.fill(email)
            if pwd_input: pwd_input.fill(pwd)
            signin_btn.click()
            time.sleep(3.0)
            return True

    return False


# ---------------------------------------------------------------------------
# Generic Field Detection & Heuristics Engine
# ---------------------------------------------------------------------------

def extract_field_label(group) -> str:
    """Extract human-readable label from element or parent container."""
    # Check explicit label or legend
    lbl = group.query_selector("label, legend, [class*='label'], [data-automation-id*='label']")
    if lbl:
        txt = lbl.inner_text().strip()
        if txt:
            return txt

    # Check attributes
    for attr in ["aria-label", "placeholder", "title", "name", "id"]:
        val = group.get_attribute(attr) if hasattr(group, "get_attribute") else None
        if val and len(val) > 1 and not val.startswith("http"):
            return val.strip()

    return ""


def derive_from_cv_heuristics(label: str, cv_data: Dict[str, Any]) -> Optional[str]:
    """Derive standard field answers directly from CV JSON based on label keywords."""
    norm = normalize_label(label)
    full_name = cv_data.get("name", "")
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    contact_info = cv_data.get("contact_info", "")
    contact_str = " | ".join(contact_info) if isinstance(contact_info, list) else str(contact_info)

    # Email
    if "email" in norm:
        match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", contact_str)
        return match.group(0) if match else None

    # Phone
    if "phone" in norm or "mobile" in norm or "telephone" in norm:
        match = re.search(r"[\+\d][\d\s\-\(\)]{6,}", contact_str)
        return match.group(0).strip() if match else None

    # First Name
    if "first name" in norm or "given name" in norm:
        return first_name

    # Last Name
    if "last name" in norm or "surname" in norm or "family name" in norm:
        return last_name

    # Full Name
    if norm in ("name", "full name", "your name"):
        return full_name

    # LinkedIn
    if "linkedin" in norm:
        match = re.search(r"https?://[^\s]*linkedin[^\s]*", contact_str)
        return match.group(0) if match else "https://linkedin.com"

    # City / Location
    if "city" in norm or "location" in norm:
        match = re.search(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2,})", contact_str)
        return match.group(0) if match else None

    return None


def is_search_or_nav_field(el, label: str) -> bool:
    """Return True if element is a site search box, navigation bar input, or filter field."""
    norm = normalize_label(label)
    if norm in ("search", "search jobs", "search careers", "filter", "filter jobs", "ieskoti", "paieska", "query", "keywords"):
        return True

    try:
        el_type = (el.get_attribute("type") or "").lower()
        if el_type in ("search", "button", "reset"):
            return True

        for attr in ["name", "id", "placeholder", "aria-label", "class"]:
            val = (el.get_attribute(attr) or "").lower()
            if any(k in val for k in ["nav-search", "header-search", "site-search", "top-search", "search-input", "global-search", "searchbox"]):
                return True
    except Exception:
        pass

    return False


def fill_element_robustly(el, value: str) -> None:
    """
    Fill input element robustly by focusing, setting value, dispatching input & change events,
    and blurring so React/Angular/Vue reactive forms persist the typed value without clearing it.
    """
    val_str = str(value)
    try:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        el_type = (el.get_attribute("type") or "").lower()

        if tag == "select":
            try: el.select_option(value=val_str)
            except Exception: el.select_option(label=val_str)
        elif el_type in ("checkbox", "radio"):
            if val_str.lower() in ("yes", "true", "1") and not el.is_checked():
                el.click()
        else:
            el.focus()
            el.fill("")
            time.sleep(0.1)
            el.fill(val_str)
            el.dispatch_event("input")
            el.dispatch_event("change")
            el.blur()
    except Exception as e:
        print(f"[guided_applier] Fill warning, fallback to direct fill: {e}")
        try:
            el.fill(val_str)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main Guided Application Orchestrator
# ---------------------------------------------------------------------------

def run_guided_apply_session(
    session_id: str,
    portal_url: str,
    cv_data: Dict[str, Any],
    pdf_path: str,
    company: str,
    li_at: str
) -> None:
    """
    Background worker function managing Playwright browser session for guided portal apply.
    Updates ACTIVE_SESSIONS status dict and persists to data/portal_sessions/.
    """
    memory = load_answers_memory()
    audit_dir = os.path.join("data", "applications", f"{company}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}")
    os.makedirs(audit_dir, exist_ok=True)

    filled_fields: Dict[str, Any] = {}
    screenshots: List[str] = []

    # Update active session entry
    with ACTIVE_SESSIONS_LOCK:
        ACTIVE_SESSIONS[session_id] = {
            "session_id": session_id,
            "company": company,
            "portal_url": portal_url,
            "status": "running",
            "current_step": 1,
            "total_steps": 4,
            "last_action": "Launching Chromium browser...",
            "paused_field": None,
            "filled_fields": filled_fields,
            "screenshots": screenshots,
            "audit_dir": audit_dir
        }

    save_session(company, portal_url, 1, 4, filled_fields, "running", session_id=session_id)

    # Fallback li_at cookie from memory if not provided in request
    cookie_val = (li_at or "").strip()
    if not cookie_val or cookie_val.lower() in ("none", "null", "undefined"):
        cookie_val = memory.get("linkedin_li_at_cookie", "").strip()
    elif cookie_val:
        memory["linkedin_li_at_cookie"] = cookie_val
        save_answers_memory(memory)

    user_data_dir = os.path.abspath(os.path.join("data", "browser_profile"))
    os.makedirs(user_data_dir, exist_ok=True)

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=["--start-maximized"],
                viewport={"width": 1280, "height": 900}
            )

            # Inject li_at cookie if available
            if cookie_val and cookie_val.lower() not in ("none", "null", "undefined"):
                try:
                    context.add_cookies([{
                        "name": "li_at", "value": cookie_val, "domain": ".linkedin.com",
                        "path": "/", "expires": time.time() + 3600*24*30, "httpOnly": True, "secure": True
                    }])
                except Exception as c_err:
                    print(f"[guided_applier] Warning adding cookie: {c_err}")

            page = context.pages[0] if context.pages else context.new_page()

            try:
                print(f"[guided_applier] Navigating to {portal_url}")
                page.goto(portal_url, wait_until="domcontentloaded", timeout=35000)
                time.sleep(2.5)

                ats_type = detect_ats_platform(portal_url)
                inject_overlay(page, f"Portal loaded ({ats_type.upper()}). Scanning fields...", 1, 4)

                # Check Workday Auth
                if ats_type == "workday":
                    handle_workday_auth(page, cv_data, memory)
                    inject_overlay(page, "Workday account check completed. Scanning form...", 1, 4)

                # Loop through pages / form steps
                for step in range(1, 6):
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["current_step"] = step
                        ACTIVE_SESSIONS[session_id]["last_action"] = f"Processing step {step}..."

                    inject_overlay(page, f"Scanning step {step} inputs...", step, 4)
                    time.sleep(1.5)

                    # Check CAPTCHA
                    captcha_el = page.query_selector("iframe[src*='captcha'], div.g-recaptcha, div.h-captcha, iframe[src*='recaptcha']")
                    if captcha_el and captcha_el.is_visible():
                        screenshot_path, b64 = highlight_element_and_screenshot(page, captcha_el, audit_dir, f"captcha_step{step}")
                        screenshots.append(screenshot_path)

                        paused_info = {
                            "label": "CAPTCHA Verification Detected",
                            "field_type": "captcha",
                            "screenshot_b64": b64,
                            "options": [],
                            "selector": "captcha"
                        }

                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id]["status"] = "paused"
                            ACTIVE_SESSIONS[session_id]["paused_field"] = paused_info
                            ACTIVE_SESSIONS[session_id]["last_action"] = "Paused: CAPTCHA detected. User intervention required."

                        save_session(company, portal_url, step, 4, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                        inject_overlay(page, "⚠️ CAPTCHA detected! Please solve it in browser & click Resume in app.", step, 4)

                        # Wait for user to solve CAPTCHA and click Resume in UI
                        while True:
                            time.sleep(1.0)
                            with ACTIVE_SESSIONS_LOCK:
                                st = ACTIVE_SESSIONS[session_id]["status"]
                            if st in ("running", "cancelled", "completed"):
                                break
                            if st == "stopped":
                                context.close()
                                return

                    # Handle File Upload on this step if present
                    file_input = page.query_selector("input[type='file']")
                    if file_input and os.path.exists(pdf_path):
                        try:
                            file_input.set_input_files(os.path.abspath(pdf_path))
                            filled_fields["Resume / CV Upload"] = os.path.basename(pdf_path)
                            time.sleep(2.0)
                        except Exception as fu_err:
                            print(f"[guided_applier] File upload warning: {fu_err}")

                    # Scan form inputs on page
                    inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']), select, textarea")
                    for el in inputs:
                        if not el.is_visible():
                            continue

                        label = extract_field_label(el)
                        if not label:
                            continue

                        # Ignore site search bars, navigation header inputs, or filter queries
                        if is_search_or_nav_field(el, label):
                            continue

                        # Skip if already filled in this session or has value
                        if label in filled_fields and filled_fields[label]:
                            continue

                        try:
                            curr_val = el.input_value() if el.tag_name in ("input", "textarea") else ""
                            if curr_val and len(curr_val) > 0:
                                continue
                        except Exception:
                            pass

                        # 1. Try fuzzy lookup in answers memory
                        ans, score = fuzzy_lookup(label, memory)

                        # 2. Try CV heuristics if memory lookup failed
                        if not ans:
                            ans = derive_from_cv_heuristics(label, cv_data)

                        if ans:
                            # Fill field robustly with reactive event dispatches
                            fill_element_robustly(el, ans)
                            filled_fields[label] = ans
                            memory[normalize_label(label)] = str(ans)
                            save_answers_memory(memory)
                            time.sleep(0.4)

                        else:
                            # Pause on unknown field!
                            screenshot_path, b64 = highlight_element_and_screenshot(page, el, audit_dir, f"pause_step{step}_{len(filled_fields)}")
                            screenshots.append(screenshot_path)

                            # Determine options for select / radio
                            options = []
                            if el.evaluate("el => el.tagName.toLowerCase()") == "select":
                                opts = el.query_selector_all("option")
                                options = [o.inner_text().strip() for o in opts if o.inner_text().strip()]

                            paused_info = {
                                "label": label,
                                "field_type": el.get_attribute("type") or el.evaluate("el => el.tagName.toLowerCase()"),
                                "screenshot_b64": b64,
                                "options": options,
                                "selector": label
                            }

                            with ACTIVE_SESSIONS_LOCK:
                                ACTIVE_SESSIONS[session_id]["status"] = "paused"
                                ACTIVE_SESSIONS[session_id]["paused_field"] = paused_info
                                ACTIVE_SESSIONS[session_id]["last_action"] = f"Paused on field: '{label}'"

                            save_session(company, portal_url, step, 4, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                            inject_overlay(page, f"Paused on: '{label}'. Please answer in main console.", step, 4)

                            # Wait for user answer via POST /api/answer-field
                            while True:
                                time.sleep(1.0)
                                with ACTIVE_SESSIONS_LOCK:
                                    st = ACTIVE_SESSIONS[session_id]["status"]
                                    user_ans = ACTIVE_SESSIONS[session_id].get("latest_user_answer")

                                if user_ans and st == "running":
                                    # Inject user provided answer robustly
                                    try:
                                        fill_element_robustly(el, user_ans)
                                        filled_fields[label] = user_ans
                                        if ACTIVE_SESSIONS[session_id].get("remember_answer", True):
                                            memory[normalize_label(label)] = user_ans
                                            save_answers_memory(memory)
                                    except Exception as inject_err:
                                        print(f"[guided_applier] Error injecting answer: {inject_err}")

                                    # Clear latest answer flag
                                    with ACTIVE_SESSIONS_LOCK:
                                        ACTIVE_SESSIONS[session_id]["latest_user_answer"] = None
                                        ACTIVE_SESSIONS[session_id]["paused_field"] = None
                                    break

                                if st in ("cancelled", "stopped"):
                                    context.close()
                                    return

                    # Take step completion screenshot
                    p_path = os.path.join(audit_dir, f"step_{step}_complete.png")
                    page.screenshot(path=p_path, full_page=False)
                    screenshots.append(p_path)

                    # Look for Next / Submit / Continue button
                    next_btn = page.query_selector(
                        "button[data-automation-id='bottom-navigation-next-button'], "
                        "button:has-text('Next'), button:has-text('Continue'), "
                        "button:has-text('Submit'), input[type='submit']"
                    )

                    if next_btn and next_btn.is_visible():
                        inject_overlay(page, f"Advancing step {step}...", step, 4)
                        next_btn.click()
                        time.sleep(2.5)
                    else:
                        print(f"[guided_applier] No more Next buttons visible on step {step}.")
                        break

                # Application finished
                with ACTIVE_SESSIONS_LOCK:
                    ACTIVE_SESSIONS[session_id]["status"] = "completed"
                    ACTIVE_SESSIONS[session_id]["last_action"] = "Application process completed!"

                save_session(company, portal_url, 4, 4, filled_fields, "completed", session_id=session_id)
                inject_overlay(page, "🎉 Application Completed! You may review & close.", 4, 4)
                time.sleep(5.0)

            finally:
                context.close()

    except Exception as err:
        import traceback
        err_msg = f"{err}\n{traceback.format_exc()}"
        print(f"[guided_applier] Error in guided apply session: {err_msg}")
        with ACTIVE_SESSIONS_LOCK:
            ACTIVE_SESSIONS[session_id]["status"] = "failed"
            ACTIVE_SESSIONS[session_id]["last_action"] = f"Error: {err}"
        save_session(company, portal_url, 1, 4, filled_fields, "failed", session_id=session_id)


def start_guided_apply(
    portal_url: str,
    cv_data: Dict[str, Any],
    pdf_path: str,
    company: str = "Company",
    li_at: str = ""
) -> str:
    """Public entry point: starts run_guided_apply_session in background thread."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_comp = re.sub(r'[^a-zA-Z0-9_]', '_', company)
    session_id = f"{safe_comp}_{ts}"

    def wrapper():
        import sys, asyncio
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass
        run_guided_apply_session(session_id, portal_url, cv_data, pdf_path, company, li_at)

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    return session_id
