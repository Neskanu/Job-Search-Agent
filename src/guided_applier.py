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
import urllib.parse
from datetime import datetime
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, Page, Browser
from PIL import Image, ImageDraw
from src.browser_manager import create_browser_context, prepare_linkedin_cookies, cleanup_profile_locks, ensure_linkedin_session


# ---------------------------------------------------------------------------
# Global Session Memory & Active Session Registry
# ---------------------------------------------------------------------------

MEMORY_FILE_PATH = os.path.join("data", "answers_memory.json")
SESSIONS_DIR = os.path.join("data", "portal_sessions")

# Active runtime session store for API status polling
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
ACTIVE_SESSIONS_LOCK = threading.Lock()


def log_action(session_id: str, msg: str) -> None:
    """Log real-time action timestamp into active session store."""
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(f"[guided_applier] {entry}")
    with ACTIVE_SESSIONS_LOCK:
        if session_id in ACTIVE_SESSIONS:
            if "logs" not in ACTIVE_SESSIONS[session_id]:
                ACTIVE_SESSIONS[session_id]["logs"] = []
            ACTIVE_SESSIONS[session_id]["logs"].append(entry)
            if len(ACTIVE_SESSIONS[session_id]["logs"]) > 50:
                ACTIVE_SESSIONS[session_id]["logs"] = ACTIVE_SESSIONS[session_id]["logs"][-50:]
            ACTIVE_SESSIONS[session_id]["last_action"] = msg


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


def fuzzy_lookup(label: str, memory: Dict[str, str], threshold: float = 0.85) -> Tuple[Optional[str], float]:
    """
    Find best matching answer in memory using a combination of difflib SequenceMatcher
    and token set similarity on normalized label strings.
    Returns (answer, match_score) or (None, best_score). Higher 0.85 threshold prevents
    false matches between sponsorship and work authorization questions.
    """
    norm_target = normalize_label(label)
    if not norm_target or not memory:
        return None, 0.0

    target_tokens = set(norm_target.split())
    best_score = 0.0
    best_value = None

    for raw_key, value in memory.items():
        if not value or raw_key == "workday_password":
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

def is_target_closed_error(e: Exception) -> bool:
    """Check if exception is caused by target page, context, browser being closed, or navigation context destruction."""
    if not e:
        return False
    msg = str(e).lower()
    closed_keywords = (
        "target page, context or browser has been closed",
        "target closed",
        "browser has been closed",
        "context has been closed",
        "page has been closed",
        "has been closed",
        "connection closed",
        "execution context was destroyed",
        "most likely because of a navigation"
    )
    return any(k in msg for k in closed_keywords)


def get_active_page(context, current_page: Optional[Page] = None, prefer_latest: bool = True) -> Optional[Page]:
    """
    Safely get an active non-closed Page object from context or current_page.
    If prefer_latest is True and context has multiple open pages, returns context.pages[-1].
    Returns None if browser context or all pages are closed.
    """
    if context:
        try:
            pages = context.pages
            open_pages = [p for p in pages if not p.is_closed()]
            if open_pages:
                if prefer_latest and len(open_pages) > 1:
                    return open_pages[-1]
                if current_page:
                    try:
                        if not current_page.is_closed():
                            return current_page
                    except Exception as e:
                        print(f"[guided_applier] Note checking current_page closed state in get_active_page: {e}")
                        pass
                return open_pages[-1]
        except Exception as e:
            print(f"[guided_applier] Note accessing context.pages in get_active_page: {e}")
            pass

    if current_page:
        try:
            if not current_page.is_closed():
                return current_page
        except Exception as e:
            print(f"[guided_applier] Note checking current_page closed state: {e}")
            pass

    return None


def inject_overlay(page: Optional[Page], message: str, step: int = 1, total_steps: int = 1) -> None:
    """Inject floating overlay control panel into live Chromium page DOM."""
    if not page:
        return
    try:
        if page.is_closed():
            return
    except Exception as e:
        print(f"[guided_applier] Note checking page.is_closed in inject_overlay: {e}")
        return

    safe_msg = message.replace('"', '\\"').replace('\n', ' ')

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
                z-index: 2147483647;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
                padding: 12px 16px;
                border-radius: 12px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
                border: 1px solid rgba(255, 255, 255, 0.15);
                max-width: 340px;
                line-height: 1.5;
                pointer-events: none;
                transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            `;
            document.body.appendChild(overlay);
        }}
        overlay.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="display:inline-block;width:8px;height:8px;background:#38bdf8;border-radius:50%;box-shadow:0 0 8px #38bdf8;"></span>
                <strong style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:#94a3b8;">Job Search Agent</strong>
                <span style="margin-left:auto;background:rgba(56,189,248,0.2);color:#38bdf8;font-size:11px;font-weight:600;padding:2px 6px;border-radius:6px;">Step {step}/{total_steps}</span>
            </div>
            <div style="font-weight:500;color:#f1f5f9;">{safe_msg}</div>
        `;
    }})();
    """
    try:
        page.evaluate(js_code)
    except Exception as e:
        if not is_target_closed_error(e):
            print(f"[guided_applier] Warning injecting overlay: {e}")


def highlight_element_and_screenshot(
    page: Optional[Page],
    selector_or_element: Any,
    audit_dir: str,
    filename_base: str
) -> Tuple[str, str]:
    """
    Take screenshot of current page, draw a red 4px rectangle around element's bounding box using PIL,
    and save image. Returns (file_path, base64_data_url).
    """
    if not page:
        return ("", "")
    try:
        if page.is_closed():
            return ("", "")
    except Exception as e:
        print(f"[guided_applier] Note checking page.is_closed in highlight_element_and_screenshot: {e}")
        return ("", "")

    os.makedirs(audit_dir, exist_ok=True)
    raw_path = os.path.join(audit_dir, f"{filename_base}_raw.png")
    out_path = os.path.join(audit_dir, f"{filename_base}.png")

    try:
        page.screenshot(path=raw_path, full_page=False)
    except Exception as s_err:
        if is_target_closed_error(s_err):
            return ("", "")
        print(f"[guided_applier] Screenshot warning: {s_err}")
        return ("", "")

    box = None
    try:
        if isinstance(selector_or_element, str):
            el = page.query_selector(selector_or_element)
            if el:
                box = el.bounding_box()
        elif hasattr(selector_or_element, "bounding_box"):
            box = selector_or_element.bounding_box()
    except Exception as err:
        if not is_target_closed_error(err):
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
    try:
        with open(out_path, "rb") as f:
            b64 = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception as e:
        print(f"[guided_applier] Failed to convert screenshot to base64 ({out_path}): {e}")
        b64 = ""

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
    if not page:
        return False
    try:
        if page.is_closed():
            return False
    except Exception as e:
        print(f"[guided_applier] Note checking page.is_closed in handle_workday_auth: {e}")
        return False

    try:
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

            # Get candidate email cleanly without dummy fallbacks
            email = memory.get("email address") or derive_from_cv_heuristics("email", cv_data) or cv_data.get("email") or ""
            if not email:
                print("[guided_applier] Warning: No candidate email available for Workday account creation.")
                return False

            # Generate password for session
            pwd = memory.get("workday_password") or generate_secure_password()

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
            email = memory.get("email address") or derive_from_cv_heuristics("email", cv_data) or ""
            pwd = memory.get("workday_password") or ""
            if email and pwd:
                email_input = page.query_selector("[data-automation-id='email']")
                pwd_input = page.query_selector("[data-automation-id='password']")
                if email_input: email_input.fill(email)
                if pwd_input: pwd_input.fill(pwd)
                signin_btn.click()
                time.sleep(3.0)
                return True
    except Exception as e:
        if not is_target_closed_error(e):
            print(f"[guided_applier] Workday auth note: {e}")

    return False


# ---------------------------------------------------------------------------
# Generic Field Detection & Heuristics Engine
# ---------------------------------------------------------------------------

def is_uuid_or_random_id(val: str) -> bool:
    """Check if a string is a UUID/GUID or random generated DOM hash id."""
    if not val:
        return True
    val_clean = val.strip().lower()
    # UUID format: e.g. a2afee6c-96db-497d-b1a9-ddb297e5e239
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', val_clean):
        return True
    # Hex string or numeric id like "input_184920" or "form-control-9482"
    if re.match(r'^(input|field|el|id|_)?[-_]?[0-9a-f]{8,32}$', val_clean):
        return True
    return False


def extract_field_label(group) -> str:
    """
    Extract human-readable label from element or nearby DOM container text,
    ignoring dynamic framework UUIDs/GUIDs.
    """
    # 1. Nearby DOM container text, aria-labelledby, or associated <label> via JS evaluation
    try:
        nearby_text = group.evaluate("""el => {
            if (el.labels && el.labels.length > 0) {
                const txt = el.labels[0].innerText ? el.labels[0].innerText.trim() : '';
                if (txt) return txt;
            }
            const lby = el.getAttribute('aria-labelledby');
            if (lby) {
                const lbyEl = document.getElementById(lby);
                if (lbyEl && lbyEl.innerText.trim()) return lbyEl.innerText.trim();
            }
            let container = el.closest('.form-group, .field, [class*="group"], [class*="field"], [data-automation-id], div, section');
            if (container) {
                const lblNode = container.querySelector('label, legend, span[class*="label"], div[class*="label"], [data-automation-id*="label"]');
                if (lblNode && lblNode.innerText.trim()) return lblNode.innerText.trim();
            }
            let prev = el.previousElementSibling;
            while (prev) {
                const txt = prev.innerText ? prev.innerText.trim() : '';
                if (txt && txt.length > 1 && txt.length < 100) return txt;
                prev = prev.previousElementSibling;
            }
            return '';
        }""")
        if nearby_text and not is_uuid_or_random_id(nearby_text):
            cleaned = re.sub(r'[\*\:]+$', '', nearby_text.strip()).strip()
            if cleaned and not is_uuid_or_random_id(cleaned):
                return cleaned
    except Exception as e:
        print(f"[guided_applier] Note evaluating nearby DOM text in extract_field_label: {e}")
        pass

    # 2. Check attributes, filtering out UUIDs
    for attr in ["aria-label", "placeholder", "title", "name", "id"]:
        val = group.get_attribute(attr) if hasattr(group, "get_attribute") else None
        if val and len(val) > 1 and not val.startswith("http") and not is_uuid_or_random_id(val):
            cleaned = re.sub(r'[\*\:]+$', '', val.strip()).strip()
            if cleaned and not is_uuid_or_random_id(cleaned):
                return cleaned

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
        if match:
            return match.group(0)
        return cv_data.get("email") or None

    # Phone
    if "phone" in norm or "mobile" in norm or "telephone" in norm:
        match = re.search(r"[\+\d][\d\s\-\(\)]{6,}", contact_str)
        if match:
            return match.group(0).strip()
        return cv_data.get("phone") or None

    # First Name
    if "first name" in norm or "given name" in norm:
        return first_name

    # Last Name
    if "last name" in norm or "surname" in norm or "family name" in norm:
        return last_name

    # Full Name
    if norm in ("name", "full name", "your name"):
        return full_name

    # LinkedIn Profile URL (Return None if missing — NEVER fallback to generic homepage!)
    if "linkedin" in norm:
        match = re.search(r"https?://[^\s]*linkedin[^\s]*", contact_str)
        if match:
            return match.group(0)
        return cv_data.get("linkedin") or cv_data.get("linkedin_url") or None

    # GitHub / Portfolio / Website
    if any(k in norm for k in ["github", "portfolio", "website", "personal site", "git"]):
        match = re.search(r"https?://[^\s]*(?:github|gitlab|portfolio|[a-zA-Z0-9-]+\.(?:io|dev|me|com))[^\s]*", contact_str)
        if match:
            return match.group(0)
        return cv_data.get("github") or cv_data.get("portfolio") or cv_data.get("website") or None

    # Current Company / Most Recent Employer
    if any(k in norm for k in ["current company", "current employer", "present employer", "company name", "most recent employer", "organization"]):
        for sec in cv_data.get("sections", []):
            if sec.get("type") == "experience":
                items = sec.get("content", [])
                if items and isinstance(items, list):
                    first_exp = items[0]
                    if isinstance(first_exp, dict) and first_exp.get("company"):
                        return first_exp["company"]

    # Current Title / Current Role
    if any(k in norm for k in ["current title", "current role", "current position", "job title", "present title", "title"]):
        for sec in cv_data.get("sections", []):
            if sec.get("type") == "experience":
                items = sec.get("content", [])
                if items and isinstance(items, list):
                    first_exp = items[0]
                    if isinstance(first_exp, dict) and first_exp.get("role"):
                        return first_exp["role"]

    # City / Location (support US & International formats e.g. Vilnius, Lithuania; London, UK)
    if "city" in norm or "location" in norm:
        match = re.search(r"([A-Z][a-zA-Z\s.-]+,\s*[A-Z][a-zA-Z\s.-]+)", contact_str)
        if match:
            return match.group(0)
        return cv_data.get("location") or cv_data.get("city") or None

    # Country
    if "country" in norm or "nation" in norm:
        if isinstance(contact_info, list):
            for ci in contact_info:
                if "," in str(ci):
                    parts = [p.strip() for p in str(ci).split(",")]
                    if len(parts) >= 2 and parts[-1] and not any(ch.isdigit() for ch in parts[-1]):
                        return parts[-1]
        match = re.search(r",\s*([A-Za-z\s.-]+?)(?:\s*\||$)", contact_str)
        if match:
            return match.group(1).strip()
        return cv_data.get("country") or None

    return None


def try_apply_with_linkedin(page: Page, context) -> bool:
    """
    Search for and click 'Apply with LinkedIn' or 'Autofill with LinkedIn' buttons
    on company portals to automatically pre-fill candidate data using logged in LinkedIn session.
    """
    active_page = get_active_page(context, page)
    if not active_page:
        return False

    selectors = [
        "button:has-text('Apply with LinkedIn')",
        "a:has-text('Apply with LinkedIn')",
        "button:has-text('Autofill with LinkedIn')",
        "a:has-text('Autofill with LinkedIn')",
        "button:has-text('Apply using LinkedIn')",
        "a:has-text('Apply using LinkedIn')",
        "[data-automation-id='applyWithLinkedIn']",
        "button[class*='linkedin']",
        "a[class*='linkedin']"
    ]

    for sel in selectors:
        try:
            active_page = get_active_page(context, active_page)
            if not active_page:
                return False
            btn = active_page.query_selector(sel)
            if btn and btn.is_visible():
                print(f"[guided_applier] Detected 'Apply with LinkedIn' button ({sel}). Executing click...")
                inject_overlay(active_page, "Clicking 'Apply with LinkedIn' to auto-fill details...", 1, 4)
                pages_before = len(context.pages) if context else 0
                btn.click()
                time.sleep(3.0)

                if context and len(context.pages) > pages_before:
                    popup = context.pages[-1]
                    print(f"[guided_applier] LinkedIn OAuth popup detected: {popup.url}")
                    popup.wait_for_load_state("domcontentloaded", timeout=15000)
                    time.sleep(2.0)

                    allow_btn = popup.query_selector("button:has-text('Allow'), input[value='Allow'], button:has-text('Continue'), button:has-text('Sign In')")
                    if allow_btn and allow_btn.is_visible():
                        allow_btn.click()
                        time.sleep(3.0)

                return True
        except Exception as e:
            if not is_target_closed_error(e):
                print(f"[guided_applier] 'Apply with LinkedIn' note: {e}")

    return False


def is_search_or_nav_field(el, label: str) -> bool:
    """Return True if element is a site search box, navigation bar input, filter, footer, or language selector."""
    norm = normalize_label(label)
    if not norm or len(norm) < 2 or norm in ("search", "search jobs", "search careers", "filter", "filter jobs", "ieskoti", "paieska", "query", "keywords", "r4", "language", "kalba"):
        return True

    # Check bounding box size (skip tiny/hidden icons)
    try:
        box = el.bounding_box()
        if box and (box.get("width", 0) < 15 or box.get("height", 0) < 15):
            return True
    except Exception as e:
        print(f"[guided_applier] Note checking bounding box in is_search_or_nav_field: {e}")
        pass

    try:
        el_type = (el.get_attribute("type") or "").lower()
        if el_type in ("search", "button", "reset"):
            return True

        # Check if element is inside header, footer, or nav block
        try:
            is_in_nav = el.evaluate("""el => {
                const container = el.closest('header, footer, nav, [role="contentinfo"], [role="navigation"], .footer, .header, #footer, #header');
                return container !== null;
            }""")
            if isinstance(is_in_nav, bool) and is_in_nav:
                return True
        except Exception as e:
            print(f"[guided_applier] Note evaluating is_in_nav in is_search_or_nav_field: {e}")
            pass

        for attr in ["name", "id", "placeholder", "aria-label", "class"]:
            val = (el.get_attribute(attr) or "").lower()
            if any(k in val for k in ["nav-search", "header-search", "site-search", "top-search", "search-input", "global-search", "searchbox", "lang-select", "language-selector", "footer-lang", "footer"]):
                return True

        # Check options for language selectors (e.g. Arabic, English, Lithuanian)
        if el.evaluate("el => el.tagName.toLowerCase()") == "select":
            opt_texts = [o.inner_text().strip().lower() for o in el.query_selector_all("option")[:5]]
            if any(lang in opt for opt in opt_texts for lang in ["arabic", "english", "lithuanian", "lietuvių", "deutsch", "español", "francais"]):
                return True
    except Exception as e:
        print(f"[guided_applier] Note checking attributes in is_search_or_nav_field: {e}")
        pass

    return False


def fill_element_robustly(el, value: str) -> None:
    """
    Fill input element robustly by focusing, setting value, dispatching input & change events,
    and blurring so React/Angular/Vue reactive forms persist the typed value without clearing it.
    Matches dropdown <select> options against both value and visible text.
    """
    val_str = str(value).strip()
    try:
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        el_type = (el.get_attribute("type") or "").lower()

        if tag == "select":
            # Match options by value or visible text
            options_info = el.evaluate("""sel => {
                return Array.from(sel.options).map((o, idx) => ({
                    index: idx,
                    value: o.value,
                    text: o.innerText.trim()
                }));
            }""")
            matched_val = None
            for opt in options_info:
                if val_str.lower() == opt["value"].lower() or val_str.lower() == opt["text"].lower():
                    matched_val = opt["value"]
                    break
            if not matched_val:
                for opt in options_info:
                    if val_str.lower() in opt["text"].lower() or opt["text"].lower() in val_str.lower():
                        matched_val = opt["value"]
                        break
            if matched_val:
                el.select_option(value=matched_val)
            else:
                try:
                    el.select_option(value=val_str)
                except Exception as e_val:
                    try:
                        el.select_option(label=val_str)
                    except Exception as e_lbl:
                        print(f"[guided_applier] Failed to select option by value ({e_val}) and label ({e_lbl}) for '{val_str}'")
                        pass

        elif el_type in ("checkbox", "radio"):
            is_affirmative = val_str.lower() in ("yes", "true", "1")
            is_negative = val_str.lower() in ("no", "false", "0")
            if is_affirmative and not el.is_checked():
                el.click()
            elif is_negative and el.is_checked():
                el.click()
        else:
            el.focus()
            el.fill(val_str)
            el.evaluate("""el => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
            el.blur()
    except Exception as err:
        print(f"[guided_applier] Fill note for '{value}': {err}")
        try:
            el.fill(val_str)
        except Exception as fallback_err:
            print(f"[guided_applier] Fallback fill failed for '{val_str}': {fallback_err}")
            pass



def safe_goto(
    page: Page,
    url: str,
    timeout: int = 35000,
    session_id: str = ""
) -> bool:
    """
    Safely navigate to a URL.
    Important:
    - Does NOT retry redirect loops.
    - Returns False for chrome-error:// and about:blank.
    - Logs final URL, HTTP status, and navigation exceptions.
    """
    if not url or not url.startswith("http"):
        if session_id:
            log_action(session_id, f"Invalid portal URL: {url}")
        else:
            print(f"[guided_applier] Invalid portal URL: {url}")
        return False

    try:
        if session_id:
            log_action(session_id, f"Navigating to {url}")
        else:
            print(f"[guided_applier] Navigating to {url}")

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout
        )

        final_url = page.url

        if final_url.startswith("chrome-error://"):
            msg = f"Chromium navigation error page: {final_url}"
            if session_id: log_action(session_id, msg)
            else: print(f"[guided_applier] {msg}")
            return False

        if final_url == "about:blank":
            msg = "Navigation resulted in about:blank"
            if session_id: log_action(session_id, msg)
            else: print(f"[guided_applier] {msg}")
            return False

        if response:
            msg = f"Navigation completed: HTTP {response.status} -> {final_url}"
            if session_id: log_action(session_id, msg)
            else: print(f"[guided_applier] {msg}")
        else:
            msg = f"Navigation completed without response object: {final_url}"
            if session_id: log_action(session_id, msg)
            else: print(f"[guided_applier] {msg}")

        return True

    except Exception as e:
        error_text = str(e)
        msg = f"Navigation failed: {error_text}"
        if session_id: log_action(session_id, msg)
        else: print(f"[guided_applier] {msg}")

        if any(term in error_text.lower() for term in (
            "too many redirects",
            "err_too_many_redirects",
            "redirect loop",
        )):
            loop_msg = "Redirect loop detected. Navigation will NOT be retried."
            if session_id: log_action(session_id, loop_msg)
            else: print(f"[guided_applier] {loop_msg}")

        return False


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

    TOTAL_STEPS = 5
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
            "total_steps": TOTAL_STEPS,
            "last_action": "Launching Chromium browser...",
            "paused_field": None,
            "filled_fields": filled_fields,
            "screenshots": screenshots,
            "audit_dir": audit_dir,
            "logs": []
        }

    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "running", session_id=session_id)

    # Fallback li_at cookie from memory if not provided in request
    cookie_val = (li_at or "").strip().strip('"').strip("'")
    if not cookie_val or cookie_val.lower() in ("none", "null", "undefined"):
        cookie_val = memory.get("linkedin_li_at_cookie", "").strip().strip('"').strip("'")
    elif cookie_val:
        memory["linkedin_li_at_cookie"] = cookie_val
        save_answers_memory(memory)

    # Single persistent browser profile directory so logins/sessions are saved across runs
    user_data_dir = os.path.abspath(os.path.join("data", "browser_profile"))
    os.makedirs(user_data_dir, exist_ok=True)

    try:
        with sync_playwright() as pw:
            context = create_browser_context(pw, user_data_dir)

            # Perform main domain handshake if target URL is LinkedIn to establish full session state
            if "linkedin.com" in portal_url.lower():
                ensure_linkedin_session(context, cookie_val, lambda msg: log_action(session_id, msg))

            page = get_active_page(context)
            if not page:
                page = context.new_page()

            # Dynamically track newly opened tabs (e.g. ATS redirects)
            try:
                context.on("page", lambda p: log_action(session_id, f"New tab event: {p.url}"))
            except Exception as e:
                print(f"[guided_applier] Failed to register tab event listener: {e}")
                pass

            try:
                log_action(session_id, f"Navigating to {portal_url}...")
                ok = safe_goto(page, portal_url, session_id=session_id)
                page = get_active_page(context, page)
                if not page:
                    log_action(session_id, "Target page or browser closed during initial navigation.")
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window or tab closed."
                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                    return

                if not ok:
                    current_url = page.url if page else "unknown"
                    log_action(session_id, f"Initial navigation failed. Current URL: {current_url}")

                    if "linkedin.com" in portal_url.lower():
                        log_action(
                            session_id,
                            "LinkedIn navigation failed. "
                            "This is likely an authentication/cookie/profile problem. "
                            "Stopping instead of retrying the redirect loop."
                        )

                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "failed"
                        ACTIVE_SESSIONS[session_id]["last_action"] = f"Navigation failed: {current_url}"

                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "failed", session_id=session_id)
                    return

                log_action(session_id, f"Page loaded: {page.url}")
                time.sleep(2.5)

                page = get_active_page(context, page)
                if not page:
                    log_action(session_id, "Target page or browser closed after initial load.")
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window or tab closed."
                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                    return

                # Check if page rendered blank white and reload if needed
                try:
                    body_text = page.locator("body").inner_text().strip()
                    if not body_text:
                        log_action(session_id, "Blank page detected. Reloading page...")
                        page.reload(wait_until="domcontentloaded", timeout=20000)
                        time.sleep(2.0)
                except Exception as e:
                    print(f"[guided_applier] Note while checking blank page body / reload: {e}")
                    pass

                page = get_active_page(context, page)
                if not page:
                    log_action(session_id, "Target page or browser closed.")
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window or tab closed."
                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                    return

                # Dismiss cookie/modal overlays if present
                try:
                    page = get_active_page(context, page)
                    if page:
                        dismiss_btns = page.query_selector_all(
                            "button.modal__dismiss, button[aria-label='Dismiss'], button[aria-label='Close'], "
                            "button.contextual-sign-in-modal__modal-dismiss, #onetrust-accept-btn-handler, "
                            "button:has-text('Accept Cookies'), button:has-text('Accept all')"
                        )
                        for d in dismiss_btns:
                            try:
                                if d.is_visible(): d.click(force=True)
                            except Exception as d_err:
                                print(f"[guided_applier] Note dismissing button: {d_err}")
                                pass
                except Exception as e:
                    print(f"[guided_applier] Note querying dismiss buttons: {e}")
                    pass

                # If on a job description page (LinkedIn or company portal), locate and trigger Apply button
                log_action(session_id, f"Scanning for initial Apply button (page: {page.url if page else 'unknown'})...")
                inject_overlay(page, "Locating Apply button...", 1, TOTAL_STEPS)

                apply_selectors = [
                    # LinkedIn external / guest / standard
                    "a.apply-button",
                    "button.apply-button",
                    "a[data-tracking-control-name*='apply']",
                    "a:has-text('Apply on company website')",
                    "button:has-text('Apply on company website')",
                    "a[href*='/jobs/view/externalApply']",
                    "button.jobs-apply-button",
                    "a.jobs-apply-button",
                    "a[href*='/jobs/apply']",
                    ".top-card-layout__cta",
                    # Workday
                    "[data-automation-id='adventureButton']",
                    "a[data-automation-id='jobPostingApplyButton']",
                    "button[data-automation-id='jobPostingApplyButton']",
                    "a:has-text('Apply Manually')",
                    "button:has-text('Apply Manually')",
                    "a:has-text('Apply with LinkedIn')",
                    # Lever
                    "a.postings-btn[href*='/apply']",
                    "a:has-text('Apply for this job')",
                    ".postings-btn",
                    # Greenhouse
                    "a[href='#app']",
                    "button#apply_button",
                    # Generic
                    "button:has-text('Apply Now')",
                    "a:has-text('Apply Now')",
                    "button:has-text('Apply')",
                    "a:has-text('Apply')"
                ]

                visible_apply_btn = None
                for sel in apply_selectors:
                    page = get_active_page(context, page)
                    if not page: break
                    try:
                        elements = page.query_selector_all(sel)
                        for el in elements:
                            try:
                                if el.is_visible():
                                    txt = el.inner_text().strip().lower()
                                    if not any(ign in txt for ign in ["filter", "coupon", "setting", "easy apply"]):
                                        visible_apply_btn = el
                                        break
                            except Exception as e_el:
                                print(f"[guided_applier] Note checking apply button element: {e_el}")
                                pass
                        if visible_apply_btn: break
                    except Exception as sel_err:
                        if is_target_closed_error(sel_err):
                            page = get_active_page(context, page)
                            if not page: break

                if visible_apply_btn:
                    log_action(session_id, "Found visible Apply button. Navigating / clicking link...")
                    inject_overlay(page, "Clicking Apply link to open application form...", 1, TOTAL_STEPS)
                    try:
                        target_href = None
                        try:
                            target_href = visible_apply_btn.get_attribute("href")
                        except Exception as e_href:
                            print(f"[guided_applier] Note getting apply button href: {e_href}")
                            pass

                        if target_href and target_href.strip() and not target_href.startswith("javascript:") and not target_href.startswith("#"):
                            full_target_url = urllib.parse.urljoin(page.url, target_href)
                            log_action(session_id, f"Navigating directly via Apply link href -> {full_target_url}")
                            safe_goto(page, full_target_url)
                            time.sleep(3.0)
                        else:
                            try:
                                with context.expect_page(timeout=5000) as page_info:
                                    visible_apply_btn.click(force=True)
                                new_p = page_info.value
                                new_p.wait_for_load_state("domcontentloaded", timeout=15000)
                                page = new_p
                                log_action(session_id, f"Redirected to new tab: {page.url}")
                            except Exception:
                                time.sleep(2.5)

                        # Check if an intermediate redirect dialog appeared (e.g. LinkedIn "Continue to company website")
                        page = get_active_page(context, page)
                        if page:
                            try:
                                cont_btns = page.query_selector_all(
                                    "button:has-text('Continue'), a:has-text('Continue'), "
                                    "button:has-text('Proceed'), a:has-text('Proceed'), "
                                    "button:has-text('Go to company website'), "
                                    "button[data-control-name*='continue']"
                                )
                                for cb in cont_btns:
                                    if cb.is_visible():
                                        log_action(session_id, "Clicking intermediate redirect confirmation button...")
                                        try:
                                            with context.expect_page(timeout=5000) as c_info:
                                                cb.click(force=True)
                                            page = c_info.value
                                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                                            log_action(session_id, f"Redirected to portal tab: {page.url}")
                                        except Exception:
                                            time.sleep(2.0)
                                        break
                            except Exception as e_cont:
                                print(f"[guided_applier] Note clicking continue button: {e_cont}")
                                pass

                        # Check if any external page opened in context
                        if context:
                            open_pages = [p for p in context.pages if not p.is_closed()]
                            ext_pages = [p for p in open_pages if "linkedin.com/jobs" not in p.url.lower() and p.url != "about:blank"]
                            if ext_pages:
                                page = ext_pages[-1]
                                log_action(session_id, f"Switched to application portal tab: {page.url}")

                    except Exception as apply_err:
                        log_action(session_id, f"Apply click note: {apply_err}")
                        time.sleep(2.0)

                page = get_active_page(context, page)
                if not page:
                    log_action(session_id, "Target page or browser closed.")
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed."
                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                    return

                # If still stuck on LinkedIn page without external portal redirect, pause for human handholding in live browser
                if "linkedin.com" in page.url.lower():
                    screenshot_path, b64 = highlight_element_and_screenshot(page, visible_apply_btn or page.query_selector("body"), audit_dir, "linkedin_handshake")
                    if screenshot_path: screenshots.append(screenshot_path)

                    paused_info = {
                        "label": "Click 'Apply' on LinkedIn page in Chromium",
                        "field_type": "text",
                        "screenshot_b64": b64,
                        "options": [],
                        "selector": "linkedin_apply"
                    }

                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "paused"
                        ACTIVE_SESSIONS[session_id]["paused_field"] = paused_info
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Paused: Click Apply in browser window to open portal, then Resume."

                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                    inject_overlay(page, "👉 Please click the Apply button in Chromium to open portal, then click Resume →", 1, TOTAL_STEPS)

                    # Keep browser open and wait for user to resume or navigate
                    while True:
                        time.sleep(1.0)
                        page = get_active_page(context, page)
                        if not page:
                            log_action(session_id, "Browser closed by user while paused on LinkedIn.")
                            with ACTIVE_SESSIONS_LOCK:
                                ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                                ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                            save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                            return

                        # Check if user clicked apply and external tab opened in the meantime
                        if context:
                            open_p = [p for p in context.pages if not p.is_closed()]
                            ext_p = [p for p in open_p if "linkedin.com" not in p.url.lower() and p.url != "about:blank"]
                            if ext_p:
                                page = ext_p[-1]
                                log_action(session_id, f"Detected external portal tab opened by user: {page.url}")
                                with ACTIVE_SESSIONS_LOCK:
                                    ACTIVE_SESSIONS[session_id]["status"] = "running"
                                    ACTIVE_SESSIONS[session_id]["paused_field"] = None
                                break

                        with ACTIVE_SESSIONS_LOCK:
                            st = ACTIVE_SESSIONS[session_id]["status"]
                        if st in ("running", "cancelled", "completed"):
                            break
                        if st == "stopped":
                            try:
                                context.close()
                            except Exception as e_close:
                                print(f"[guided_applier] Note closing context on pause stop: {e_close}")
                                pass
                            return

                    # Re-check active page after resume
                    page = get_active_page(context, page)
                    if not page: return
                    if context:
                        open_p = [p for p in context.pages if not p.is_closed()]
                        ext_p = [p for p in open_p if "linkedin.com" not in p.url.lower() and p.url != "about:blank"]
                        if ext_p:
                            page = ext_p[-1]
                            log_action(session_id, f"Switched to external portal tab: {page.url}")

                ats_type = detect_ats_platform(page.url)
                log_action(session_id, f"Portal loaded ({ats_type.upper()}: {page.url}). Scanning fields...")
                inject_overlay(page, f"Portal loaded ({ats_type.upper()}). Scanning fields...", 1, TOTAL_STEPS)

                # 1. Always attempt 'Apply with LinkedIn' / 'Autofill with LinkedIn' on external portal
                try_apply_with_linkedin(page, context)
                page = get_active_page(context, page)
                if not page:
                    log_action(session_id, "Browser closed during Apply with LinkedIn.")
                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                    save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                    return

                # 2. Check Workday Auth
                if ats_type == "workday":
                    handle_workday_auth(page, cv_data, memory)
                    page = get_active_page(context, page)
                    if not page:
                        log_action(session_id, "Browser closed during Workday auth.")
                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                            ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                        save_session(company, portal_url, 1, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                        return
                    inject_overlay(page, "Workday account check completed. Scanning form...", 1, TOTAL_STEPS)

                # Loop through pages / form steps
                for step in range(1, TOTAL_STEPS + 1):
                    log_action(session_id, f"Processing form step {step}/{TOTAL_STEPS}...")
                    page = get_active_page(context, page)
                    if not page:
                        log_action(session_id, f"Browser closed at step {step}.")
                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                            ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                        save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                        return

                    with ACTIVE_SESSIONS_LOCK:
                        ACTIVE_SESSIONS[session_id]["current_step"] = step
                        ACTIVE_SESSIONS[session_id]["last_action"] = f"Processing step {step}..."

                    inject_overlay(page, f"Scanning step {step} inputs...", step, TOTAL_STEPS)
                    time.sleep(1.5)

                    page = get_active_page(context, page)
                    if not page:
                        log_action(session_id, f"Browser closed at step {step}.")
                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                            ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                        save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                        return

                    # Check if page is stuck on a LinkedIn/Workday Login or Sign-Up Wall
                    is_login_wall = False
                    try:
                        curr_url = page.url.lower() if page else ""
                        if any(k in curr_url for k in ["linkedin.com/signup", "linkedin.com/login", "linkedin.com/uas/login"]):
                            is_login_wall = True
                        else:
                            body_text = page.locator("body").inner_text().lower() if page else ""
                            if "join linkedin now" in body_text or "sign in to linkedin" in body_text:
                                is_login_wall = True
                    except Exception as e:
                        print(f"[guided_applier] Note while checking login wall status: {e}")
                        pass

                    if is_login_wall:
                        log_action(session_id, "Login/signup wall detected. Pausing for manual sign-in...")

                        screenshot_path, b64 = highlight_element_and_screenshot(page, page.query_selector("body"), audit_dir, f"login_wall_step{step}")
                        if screenshot_path:
                            screenshots.append(screenshot_path)

                        paused_info = {
                            "label": "LinkedIn Sign-In / Authentication Required",
                            "field_type": "text",
                            "screenshot_b64": b64,
                            "options": [],
                            "selector": "linkedin_login"
                        }

                        with ACTIVE_SESSIONS_LOCK:
                            ACTIVE_SESSIONS[session_id]["status"] = "paused"
                            ACTIVE_SESSIONS[session_id]["paused_field"] = paused_info
                            ACTIVE_SESSIONS[session_id]["last_action"] = "Paused: Sign in to LinkedIn in Chromium window to proceed."

                        save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                        inject_overlay(page, "👉 Please sign in to LinkedIn in the Chromium window, then click Resume → below.", step, TOTAL_STEPS)

                        while True:
                            time.sleep(1.0)
                            page = get_active_page(context, page)
                            if not page:
                                log_action(session_id, "Browser closed by user during login wall pause.")
                                with ACTIVE_SESSIONS_LOCK:
                                    ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                                    ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                                save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                                return

                            with ACTIVE_SESSIONS_LOCK:
                                st = ACTIVE_SESSIONS[session_id]["status"]
                            if st in ("running", "cancelled", "completed"):
                                break
                            if st == "stopped":
                                try:
                                    context.close()
                                except Exception as e:
                                    print(f"[guided_applier] Note closing context on login wall stop: {e}")
                                    pass
                                return

                        # When user logs in and clicks Resume, ensure we re-navigate to the target job portal URL
                        page = get_active_page(context, page)
                        if page and portal_url:
                            curr = page.url.lower()
                            if any(k in curr for k in ["/feed", "/home", "/mynetwork", "linkedin.com/in/"]):
                                log_action(session_id, f"Login complete. Re-navigating to target job URL: {portal_url}...")
                                safe_goto(page, portal_url)
                                time.sleep(2.5)

                    # Check CAPTCHA (excluding Google Sign-in / GSI widgets)
                    captcha_el = None
                    try:
                        captcha_el = page.query_selector(
                            "iframe[src*='recaptcha/api2']:not([src*='accounts.google.com']), "
                            "iframe[src*='hcaptcha']:not([src*='accounts.google.com']), "
                            "div.g-recaptcha:not([class*='gsi']), "
                            "div.h-captcha"
                        )
                    except Exception as c_err:
                        if is_target_closed_error(c_err):
                            page = get_active_page(context, page)
                            if not page: return

                    if captcha_el and captcha_el.is_visible():
                        screenshot_path, b64 = highlight_element_and_screenshot(page, captcha_el, audit_dir, f"captcha_step{step}")
                        if screenshot_path:
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

                        save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                        inject_overlay(page, "⚠️ CAPTCHA detected! Please solve it in browser & click Resume in app.", step, TOTAL_STEPS)

                        # Wait for user to solve CAPTCHA and click Resume in UI
                        while True:
                            time.sleep(1.0)
                            page = get_active_page(context, page)
                            if not page:
                                log_action(session_id, "Browser closed by user during CAPTCHA pause.")
                                with ACTIVE_SESSIONS_LOCK:
                                    ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                                    ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                                save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                                return

                            with ACTIVE_SESSIONS_LOCK:
                                st = ACTIVE_SESSIONS[session_id]["status"]
                            if st in ("running", "cancelled", "completed"):
                                break
                            if st == "stopped":
                                try:
                                    context.close()
                                except Exception as e:
                                    print(f"[guided_applier] Note closing context on CAPTCHA stop: {e}")
                                    pass
                                return

                    # Handle File Upload on this step if present
                    page = get_active_page(context, page)
                    if not page: return

                    try:
                        file_input = page.query_selector("input[type='file']")
                        if file_input and os.path.exists(pdf_path):
                            try:
                                file_input.set_input_files(os.path.abspath(pdf_path))
                                filled_fields["Resume / CV Upload"] = os.path.basename(pdf_path)
                                time.sleep(2.0)
                            except Exception as fu_err:
                                log_action(session_id, f"File upload warning: {fu_err}")
                    except Exception as f_err:
                        if is_target_closed_error(f_err):
                            page = get_active_page(context, page)
                            if not page: return

                    # Scan form inputs on main page and any embedded frames (Greenhouse/Lever iframes)
                    inputs = []
                    try:
                        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']), select, textarea")
                    except Exception as in_err:
                        if is_target_closed_error(in_err):
                            page = get_active_page(context, page)
                            if not page: return

                    try:
                        for fr in page.frames:
                            if fr == page.main_frame:
                                continue
                            try:
                                fr_inputs = fr.query_selector_all("input:not([type='hidden']):not([type='submit']), select, textarea")
                                inputs.extend(fr_inputs)
                            except Exception as e_fr:
                                print(f"[guided_applier] Note querying frame inputs: {e_fr}")
                                pass
                    except Exception as e_frames:
                        print(f"[guided_applier] Note enumerating page frames: {e_frames}")
                        pass

                    log_action(session_id, f"Found {len(inputs)} form input fields on step {step}.")

                    for el in inputs:
                        page = get_active_page(context, page)
                        if not page: return

                        try:
                            if not el.is_visible():
                                continue
                        except Exception as vis_err:
                            if is_target_closed_error(vis_err):
                                page = get_active_page(context, page)
                                if not page: return
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

                        # Evaluate tag name and inspect existing value cleanly
                        try:
                            tag = el.evaluate("el => el.tagName.toLowerCase()")
                            el_type = (el.get_attribute("type") or "").lower()
                            if tag in ("input", "textarea", "select"):
                                try:
                                    curr_val = el.input_value()
                                except Exception as ve:
                                    curr_val = ""
                                    log_action(session_id, f"Could not inspect value for '{label}': {ve}")
                            else:
                                curr_val = ""

                            if curr_val and len(curr_val.strip()) > 0:
                                log_action(session_id, f"Field '{label}' already filled with: '{curr_val}'")
                                continue
                        except Exception as tag_err:
                            log_action(session_id, f"Tag evaluation error on '{label}': {tag_err}")
                            tag = "input"
                            el_type = "text"

                        log_action(session_id, f"Field detected: label={label!r}, tag={tag!r}, type={el_type!r}")

                        # 1. Try fuzzy lookup in answers memory
                        ans, score = fuzzy_lookup(label, memory)

                        # 2. Try CV heuristics if memory lookup failed
                        if not ans:
                            ans = derive_from_cv_heuristics(label, cv_data)
                            score = 0.9 if ans else 0.0

                        if ans:
                            log_action(session_id, f"Match for {label!r}: answer={ans!r}, score={score:.3f}")
                            fill_element_robustly(el, ans)
                            filled_fields[label] = ans

                            # Don't persist workday password to answers_memory.json
                            if normalize_label(label) != "workday_password":
                                memory[normalize_label(label)] = str(ans)
                                save_answers_memory(memory)

                            try:
                                actual = el.input_value() if tag in ("input", "textarea", "select") else "<selected>"
                            except Exception as e:
                                print(f"[guided_applier] Note reading actual filled value: {e}")
                                actual = "<unreadable>"
                            log_action(session_id, f"Filled {label!r}: requested={ans!r}, actual={actual!r}")
                            time.sleep(0.4)

                        else:
                            # Pause on unknown field!
                            screenshot_path, b64 = highlight_element_and_screenshot(page, el, audit_dir, f"pause_step{step}_{len(filled_fields)}")
                            if screenshot_path:
                                screenshots.append(screenshot_path)

                            options = []
                            try:
                                if tag == "select":
                                    opts = el.query_selector_all("option")
                                    options = [o.inner_text().strip() for o in opts if o.inner_text().strip()]
                            except Exception as e:
                                print(f"[guided_applier] Note querying select options on pause: {e}")
                                pass

                            paused_info = {
                                "label": label,
                                "field_type": el_type,
                                "screenshot_b64": b64,
                                "options": options,
                                "selector": label
                            }

                            with ACTIVE_SESSIONS_LOCK:
                                ACTIVE_SESSIONS[session_id]["status"] = "paused"
                                ACTIVE_SESSIONS[session_id]["paused_field"] = paused_info
                                ACTIVE_SESSIONS[session_id]["last_action"] = f"Paused on field: '{label}'"

                            save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "paused", paused_field=paused_info, session_id=session_id)
                            inject_overlay(page, f"Paused on: '{label}'. Please answer in main console.", step, TOTAL_STEPS)

                            # Wait for user answer via POST /api/answer-field
                            while True:
                                time.sleep(1.0)
                                page = get_active_page(context, page)
                                if not page:
                                    log_action(session_id, f"Browser closed by user while paused on '{label}'.")
                                    with ACTIVE_SESSIONS_LOCK:
                                        ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                                        ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
                                    save_session(company, portal_url, step, TOTAL_STEPS, filled_fields, "stopped", session_id=session_id)
                                    return

                                with ACTIVE_SESSIONS_LOCK:
                                    st = ACTIVE_SESSIONS[session_id]["status"]
                                    user_ans = ACTIVE_SESSIONS[session_id].get("latest_user_answer")

                                if user_ans is not None and st == "running":
                                    try:
                                        ans_str = str(user_ans).strip()
                                        if ans_str:
                                            fill_element_robustly(el, ans_str)
                                            filled_fields[label] = ans_str
                                            if ACTIVE_SESSIONS[session_id].get("remember_answer", True) and normalize_label(label) != "workday_password":
                                                memory[normalize_label(label)] = ans_str
                                                save_answers_memory(memory)
                                        else:
                                            log_action(session_id, f"Skipping optional field '{label}' (empty answer received).")
                                    except Exception as inject_err:
                                        log_action(session_id, f"Error injecting answer: {inject_err}")

                                    with ACTIVE_SESSIONS_LOCK:
                                        ACTIVE_SESSIONS[session_id]["latest_user_answer"] = None
                                        ACTIVE_SESSIONS[session_id]["paused_field"] = None
                                    break

                                if st in ("cancelled", "stopped"):
                                    try:
                                        context.close()
                                    except Exception as e:
                                        print(f"[guided_applier] Note closing context on pause cancellation: {e}")
                                        pass
                                    return

                    # Take step completion screenshot
                    page = get_active_page(context, page)
                    if not page: return

                    try:
                        p_path = os.path.join(audit_dir, f"step_{step}_complete.png")
                        page.screenshot(path=p_path, full_page=False)
                        screenshots.append(p_path)
                    except Exception as e:
                        print(f"[guided_applier] Note taking step complete screenshot: {e}")
                        pass

                    # Targeted Next / Submit / Continue button selector
                    next_btn = None
                    try:
                        next_btn = page.query_selector(
                            "button[data-automation-id='bottom-navigation-next-button'], "
                            "button[type='submit']:has-text('Submit'), "
                            "button:has-text('Submit Application'), "
                            "button:has-text('Next Step'), "
                            "button:has-text('Continue'), "
                            "input[type='submit'][value*='Submit']"
                        )
                    except Exception as nb_err:
                        if is_target_closed_error(nb_err):
                            page = get_active_page(context, page)
                            if not page: return

                    if next_btn and next_btn.is_visible():
                        log_action(session_id, f"Clicking Next/Submit button on step {step}...")
                        inject_overlay(page, f"Advancing step {step}...", step, TOTAL_STEPS)
                        old_url = page.url
                        try:
                            next_btn.click()
                        except Exception as n_err:
                            if is_target_closed_error(n_err):
                                page = get_active_page(context, page)
                                if not page: return

                        # Robust SPA wait: wait for URL change or DOM load state
                        try:
                            page.wait_for_function("old => location.href !== old", old_url, timeout=4000)
                        except Exception as e:
                            print(f"[guided_applier] Note waiting for URL change after step submission: {e}")
                            pass
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=4000)
                        except Exception as e:
                            print(f"[guided_applier] Note waiting for domcontentloaded after step submission: {e}")
                            pass
                        time.sleep(1.5)
                    else:
                        log_action(session_id, f"No more Next/Submit buttons found on step {step}. Form scanning complete.")
                        break

                # Application finished / Ready for user review
                log_action(session_id, "Form scanning and autofill completed! Visible browser window remains open for user review.")
                with ACTIVE_SESSIONS_LOCK:
                    ACTIVE_SESSIONS[session_id]["status"] = "completed"
                    ACTIVE_SESSIONS[session_id]["last_action"] = "Completed! Review application in Chromium browser window."

                save_session(company, portal_url, TOTAL_STEPS, TOTAL_STEPS, filled_fields, "completed", session_id=session_id)
                page = get_active_page(context, page)
                if page:
                    inject_overlay(page, "🎉 Form filled! Review in Chromium before final submit.", TOTAL_STEPS, TOTAL_STEPS)

                # Keep browser window open until user closes browser or stops session via UI
                while True:
                    time.sleep(1.0)
                    page = get_active_page(context, page)
                    if not page:
                        log_action(session_id, "Browser window closed by user after review.")
                        break
                    with ACTIVE_SESSIONS_LOCK:
                        st = ACTIVE_SESSIONS[session_id].get("status")
                    if st == "stopped":
                        log_action(session_id, "Session closed via UI. Closing browser window...")
                        try:
                            context.close()
                        except Exception as e:
                            print(f"[guided_applier] Note closing context on review stopped: {e}")
                            pass
                        break

            finally:
                try:
                    context.close()
                except Exception as e:
                    print(f"[guided_applier] Note closing context in finally block: {e}")
                    pass

    except Exception as err:
        if is_target_closed_error(err):
            log_action(session_id, f"Session ended cleanly (browser window or page was closed): {err}")
            with ACTIVE_SESSIONS_LOCK:
                ACTIVE_SESSIONS[session_id]["status"] = "stopped"
                ACTIVE_SESSIONS[session_id]["last_action"] = "Browser window closed by user."
            save_session(company, portal_url, 1, 4, filled_fields, "stopped", session_id=session_id)
        else:
            import traceback
            err_msg = f"{err}\n{traceback.format_exc()}"
            log_action(session_id, f"Error in guided apply session: {err_msg}")
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
            except Exception as e:
                print(f"[guided_applier] Could not set WindowsProactorEventLoopPolicy: {e}")
                pass
        run_guided_apply_session(session_id, portal_url, cv_data, pdf_path, company, li_at)

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    return session_id
