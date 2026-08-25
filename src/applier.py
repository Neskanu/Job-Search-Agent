"""
src/applier.py - LinkedIn Easy Apply Automation

Uses Playwright (sync API, run inside a thread like scraper.py) to automatically
fill in LinkedIn Easy Apply wizard forms step by step.

Key design choices:
- human_delay() adds 1-3 second random pauses between every interaction to
  mimic natural browser usage and reduce LinkedIn anti-bot detection.
- dry_run=True (default) stops just before clicking Submit and returns a
  full screenshot payload for user review. The user must explicitly confirm.
- All steps are screenshot-captured and written to data/applications/ as an
  audit trail so the user can review exactly what was submitted.
- Uses the same li_at session cookie injection pattern as scraper.py.
"""

import os
import re
import time
import random
import json
import base64
import threading
from datetime import datetime
from queue import Queue
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright, Page, Browser


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def human_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """
    Sleep for a random duration between min_sec and max_sec to mimic
    a human interacting with the browser. This helps avoid LinkedIn's
    bot-detection heuristics which look for unnaturally fast form fills.
    """
    time.sleep(random.uniform(min_sec, max_sec))


def sanitize_dirname(name: str) -> str:
    """Remove filesystem-unsafe characters from directory names."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)


def make_audit_dir(company: str) -> str:
    """
    Create and return a timestamped directory under data/applications/
    for storing screenshots and result.json for this job application.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dir_name = f"{sanitize_dirname(company)}_{ts}"
    path = os.path.join("data", "applications", dir_name)
    os.makedirs(path, exist_ok=True)
    return path


def take_step_screenshot(page: Page, audit_dir: str, step_name: str) -> str:
    """Take a screenshot of the current state and save it to the audit dir."""
    screenshot_path = os.path.join(audit_dir, f"{step_name}.png")
    page.screenshot(path=screenshot_path, full_page=False)
    return screenshot_path


def screenshot_to_base64(path: str) -> str:
    """Read a PNG screenshot and return as base64 data URL."""
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


# ---------------------------------------------------------------------------
# Browser Setup
# ---------------------------------------------------------------------------

def prepare_browser(playwright, li_at: str, headless: bool = False):
    """
    Launch Chromium and inject li_at session cookie.
    Non-headless by default so the user can watch the automation live.
    """
    browser: Browser = playwright.chromium.launch(
        headless=headless,
        args=["--start-maximized"]
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    )
    if li_at and li_at.strip().lower() not in ("", "none", "null", "undefined"):
        context.add_cookies([{
            "name": "li_at",
            "value": li_at.strip(),
            "domain": ".linkedin.com",
            "path": "/",
            "expires": time.time() + 3600 * 24 * 30,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        }])
    page = context.new_page()
    return browser, context, page


# ---------------------------------------------------------------------------
# Form Step Fillers
# ---------------------------------------------------------------------------

def fill_contact_info_step(page: Page, cv_data: Dict[str, Any]) -> None:
    """Fill Contact Info step from cv_data (name, phone). LinkedIn pre-fills email."""
    full_name = cv_data.get("name", "")
    parts = full_name.strip().split(" ", 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    contact_info = cv_data.get("contact_info", "")
    contact_str = "  |  ".join(contact_info) if isinstance(contact_info, list) else str(contact_info)
    phone_match = re.search(r"[\+\d][\d\s\-\(\)]{6,}", contact_str)
    phone = phone_match.group(0).strip() if phone_match else ""

    first_field = page.query_selector("[name='firstName'], [aria-label*='First name']")
    if first_field and not first_field.input_value():
        first_field.fill(first_name)
        human_delay(0.3, 0.8)

    last_field = page.query_selector("[name='lastName'], [aria-label*='Last name']")
    if last_field and not last_field.input_value():
        last_field.fill(last_name)
        human_delay(0.3, 0.8)

    phone_field = page.query_selector("[name='phone'], [aria-label*='Phone'], [aria-label*='Mobile']")
    if phone_field and phone and not phone_field.input_value():
        phone_field.fill(phone)
        human_delay(0.3, 0.8)

    human_delay(1.0, 2.0)


def fill_resume_step(page: Page, pdf_path: str) -> bool:
    """Upload the tailored PDF on the resume step. Returns True if uploaded."""
    abs_path = os.path.abspath(pdf_path)
    if not os.path.exists(abs_path):
        print(f"[applier] WARNING: PDF not found at {abs_path}")
        return False
    file_input = page.query_selector(
        "input[type='file'][accept*='pdf'], input[type='file'][accept*='doc'], input[type='file']"
    )
    if file_input:
        file_input.set_input_files(abs_path)
        human_delay(1.5, 3.0)
        return True
    return False


def fill_cover_letter_step(page: Page, cover_letter: str) -> bool:
    """Paste the cover letter into a cover letter textarea if one exists."""
    if not cover_letter:
        return False
    cl_field = page.query_selector(
        "textarea[aria-label*='cover letter' i], textarea[aria-label*='Cover letter' i], textarea[name*='cover']"
    )
    if cl_field:
        cl_field.fill(cover_letter)
        human_delay(0.5, 1.5)
        return True
    return False


def extract_numeric_years(text: str) -> Optional[str]:
    """Parse '6+ years', 'Over 5 years', '3-4 years' -> '6', '5', '3'. Returns None if no number."""
    match = re.search(r"(\d+)", str(text))
    return match.group(1) if match else None


def detect_and_answer_screening_questions(
    page: Page,
    cv_data: Dict[str, Any],
    answers_override: Dict[str, str]
) -> Dict[str, str]:
    """
    Scan current wizard step for employer screening questions and fill them.
    Handles: Yes/No radio, dropdown select, numeric input, text input, textarea.
    Returns dict of {question_label: answer_given} for the audit trail.
    """
    answers_given = {}

    # Estimate total years of experience from earliest experience entry
    total_years = "5"
    for sec in cv_data.get("sections", []):
        if sec.get("type") == "experience":
            all_years = []
            for item in sec.get("content", []):
                year_matches = re.findall(r"\b(20\d{2}|19\d{2})\b", item.get("period", ""))
                all_years.extend([int(y) for y in year_matches])
            if all_years:
                total_years = str(datetime.now().year - min(all_years))
            break

    form_groups = page.query_selector_all(
        ".jobs-easy-apply-form-section, [data-test-form-builder-radio-button-form-component], .fb-form-element"
    )

    for group in form_groups:
        label_el = group.query_selector("label, legend, [class*='label']")
        if not label_el:
            continue
        question_text = label_el.inner_text().strip()

        # Check user overrides first
        answer = None
        for k, v in answers_override.items():
            if k.lower() in question_text.lower():
                answer = v
                break

        # Yes/No radio
        radio_yes = group.query_selector("input[type='radio'][value='Yes'], input[type='radio'][value='yes']")
        radio_no = group.query_selector("input[type='radio'][value='No'], input[type='radio'][value='no']")
        if radio_yes and radio_no:
            if answer is None:
                answer = "Yes"
            target = radio_yes if answer.lower() in ("yes", "true", "1") else radio_no
            if not target.is_checked():
                target.click()
                human_delay(0.5, 1.5)
            answers_given[question_text] = answer
            continue

        # Dropdown
        select_el = group.query_selector("select")
        if select_el:
            if answer is None:
                opts = select_el.query_selector_all("option")
                answer = opts[1].get_attribute("value") if len(opts) > 1 else ""
            try:
                select_el.select_option(value=answer)
            except Exception as e_val:
                try:
                    select_el.select_option(label=answer)
                except Exception as e_lbl:
                    print(f"[applier] Failed to select option '{answer}' by value ({e_val}) and label ({e_lbl})")
                    pass
            human_delay(0.5, 1.0)
            answers_given[question_text] = answer
            continue

        # Numeric input
        num_input = group.query_selector("input[type='number']")
        if num_input:
            if answer is None:
                answer = extract_numeric_years(total_years) or "5"
            num_input.fill(str(answer))
            human_delay(0.3, 0.8)
            answers_given[question_text] = answer
            continue

        # Text input
        text_input = group.query_selector("input[type='text']")
        if text_input:
            existing = text_input.input_value()
            if not existing:
                if answer is None:
                    answer = cv_data.get("name", "")
                text_input.fill(str(answer))
                human_delay(0.3, 0.8)
            answers_given[question_text] = answer or existing
            continue

        # Textarea
        textarea = group.query_selector("textarea")
        if textarea:
            existing = textarea.input_value()
            if not existing and answer:
                textarea.fill(str(answer))
                human_delay(0.5, 1.5)
            answers_given[question_text] = answer or existing or ""

    return answers_given


def click_next_button(page: Page) -> bool:
    """Click Next/Continue to advance wizard. Returns True if found."""
    btn = page.query_selector(
        "button[aria-label='Continue to next step'], button[aria-label='Next'], "
        "button:has-text('Next'), button:has-text('Continue')"
    )
    if btn and btn.is_visible():
        btn.click()
        human_delay(1.5, 3.0)
        return True
    return False


def click_submit_button(page: Page) -> bool:
    """Click the Submit application button. Returns True if found."""
    btn = page.query_selector(
        "button[aria-label='Submit application'], button:has-text('Submit application'), button:has-text('Submit')"
    )
    if btn and btn.is_visible():
        btn.click()
        human_delay(2.0, 3.5)
        return True
    return False


def click_easy_apply_button(page: Page) -> bool:
    """Click the Easy Apply button to open the wizard dialog."""
    btn = page.query_selector(
        "button[data-control-name='jobdetails_topcard_inapply'], "
        "button.jobs-apply-button:has-text('Easy Apply'), button:has-text('Easy Apply')"
    )
    if btn and btn.is_visible():
        btn.click()
        human_delay(1.5, 2.5)
        return True
    return False


# ---------------------------------------------------------------------------
# Main Apply Orchestrator
# ---------------------------------------------------------------------------

def _apply_to_job_sync(
    job_url, cv_data, pdf_path, li_at, cover_letter, answers_override, dry_run, company
) -> Dict[str, Any]:
    """Internal sync function run inside a thread. Drives the full Playwright session."""
    audit_dir = make_audit_dir(company)
    screenshots = []
    screenshots_b64 = []
    screening_answers = {}
    step_reached = "init"

    try:
        with sync_playwright() as pw:
            browser, context, page = prepare_browser(pw, li_at, headless=False)
            try:
                page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                human_delay(2.0, 3.5)

                step_reached = "opening_dialog"
                if not click_easy_apply_button(page):
                    return {"success": False, "status": "no_easy_apply", "step_reached": step_reached,
                            "screenshots": [], "screenshots_b64": [], "screening_answers": {},
                            "audit_dir": audit_dir, "error": "No Easy Apply button found"}

                page.wait_for_selector(".jobs-easy-apply-modal, [data-test-modal]", timeout=10000)
                human_delay(1.5, 2.5)

                # Step 1: Contact Info
                step_reached = "contact_info"
                fill_contact_info_step(page, cv_data)
                p = take_step_screenshot(page, audit_dir, "step1_contact")
                screenshots.append(p); screenshots_b64.append(screenshot_to_base64(p))
                click_next_button(page)

                # Step 2: Resume + Cover Letter
                step_reached = "resume_upload"
                fill_resume_step(page, pdf_path)
                fill_cover_letter_step(page, cover_letter)
                p = take_step_screenshot(page, audit_dir, "step2_resume")
                screenshots.append(p); screenshots_b64.append(screenshot_to_base64(p))
                click_next_button(page)

                # Screening steps loop
                step_num = 3
                while step_num <= 8:
                    step_reached = f"screening_{step_num - 2}"
                    review_el = page.query_selector(
                        "[data-test-form-builder-component='review'], h3:has-text('Review'), h2:has-text('Review your application')"
                    )
                    if review_el:
                        break
                    fill_cover_letter_step(page, cover_letter)
                    answers = detect_and_answer_screening_questions(page, cv_data, answers_override)
                    screening_answers.update(answers)
                    p = take_step_screenshot(page, audit_dir, f"step{step_num}_screening")
                    screenshots.append(p); screenshots_b64.append(screenshot_to_base64(p))
                    if not click_next_button(page):
                        break
                    step_num += 1
                    human_delay(1.0, 2.0)

                # Review step
                step_reached = "review"
                p = take_step_screenshot(page, audit_dir, "step_review")
                screenshots.append(p); screenshots_b64.append(screenshot_to_base64(p))

                if dry_run:
                    result = {"success": True, "status": "pending_confirmation",
                              "step_reached": step_reached, "screenshots": screenshots,
                              "screenshots_b64": screenshots_b64, "screening_answers": screening_answers,
                              "audit_dir": audit_dir, "error": None}
                else:
                    submitted = click_submit_button(page)
                    step_reached = "submitted" if submitted else "submit_failed"
                    p = take_step_screenshot(page, audit_dir, "step_submitted")
                    screenshots.append(p); screenshots_b64.append(screenshot_to_base64(p))
                    result = {"success": submitted,
                              "status": "submitted" if submitted else "submit_failed",
                              "step_reached": step_reached, "screenshots": screenshots,
                              "screenshots_b64": screenshots_b64, "screening_answers": screening_answers,
                              "audit_dir": audit_dir, "error": None if submitted else "Submit button not found"}

                # Audit trail
                with open(os.path.join(audit_dir, "result.json"), "w", encoding="utf-8") as f:
                    audit = {k: v for k, v in result.items() if k != "screenshots_b64"}
                    audit.update({"job_url": job_url, "company": company, "submitted_at": datetime.now().isoformat()})
                    json.dump(audit, f, ensure_ascii=False, indent=2)

                return result
            finally:
                browser.close()

    except Exception as e:
        import traceback
        return {"success": False, "status": "failed", "step_reached": step_reached,
                "screenshots": screenshots, "screenshots_b64": screenshots_b64,
                "screening_answers": screening_answers, "audit_dir": audit_dir,
                "error": f"{e}\n{traceback.format_exc()}"}


def apply_to_job(
    job_url: str, cv_data: Dict[str, Any], pdf_path: str, li_at: str,
    cover_letter: str = "", answers_override: Optional[Dict[str, str]] = None,
    dry_run: bool = True, company: str = "Company"
) -> Dict[str, Any]:
    """
    Public entry point: runs _apply_to_job_sync in a background thread
    (same pattern as scraper.py) so the FastAPI event loop is not blocked.
    """
    if answers_override is None:
        answers_override = {}
    q: Queue = Queue()

    def wrapper():
        import sys, asyncio
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception as e:
                print(f"[applier] Could not set WindowsProactorEventLoopPolicy: {e}")
                pass
        try:
            q.put((True, _apply_to_job_sync(job_url, cv_data, pdf_path, li_at,
                                             cover_letter, answers_override, dry_run, company)))
        except Exception as e:
            import traceback
            q.put((False, {"error": str(e), "traceback": traceback.format_exc()}))

    t = threading.Thread(target=wrapper)
    t.start()
    t.join(timeout=300)

    if not q.empty():
        ok, val = q.get()
        if ok:
            return val
    return {"success": False, "status": "timeout", "step_reached": "timeout",
            "screenshots": [], "screenshots_b64": [], "screening_answers": {},
            "error": "Timed out after 300s"}


def apply_job_queue(
    job_queue: List[Dict[str, Any]], cv_data: Dict[str, Any],
    li_at: str, dry_run: bool = True
) -> List[Dict[str, Any]]:
    """
    Process a list of jobs one by one. Each item needs: job_url, company,
    job_title, pdf_path, and optionally cover_letter, answers_override.
    Returns list of result dicts in job_queue order.
    """
    results = []
    for i, job in enumerate(job_queue):
        print(f"[applier] Job {i+1}/{len(job_queue)}: {job.get('company')} — {job.get('job_title')}")
        result = apply_to_job(
            job_url=job.get("job_url", ""),
            cv_data=cv_data,
            pdf_path=job.get("pdf_path", ""),
            li_at=li_at,
            cover_letter=job.get("cover_letter", ""),
            answers_override=job.get("answers_override", {}),
            dry_run=dry_run,
            company=job.get("company", f"Company_{i+1}")
        )
        result["job_title"] = job.get("job_title", "")
        result["company"] = job.get("company", "")
        result["job_url"] = job.get("job_url", "")
        results.append(result)
        if i < len(job_queue) - 1:
            human_delay(3.0, 6.0)  # Extra delay between sequential job applications
    return results
