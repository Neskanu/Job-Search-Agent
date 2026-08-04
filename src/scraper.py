import time
import urllib.parse
from typing import List, Dict, Any, Optional
# We use the synchronous Playwright API inside our thread wrapper
from playwright.sync_api import sync_playwright

import sys
import threading
from queue import Queue

def prepare_cookies(li_at_value: str) -> List[Dict[str, Any]]:
    """Convert raw li_at cookie string to Playwright format."""
    if not li_at_value:
        return []
    cleaned_val = li_at_value.strip()
    # If the frontend passes "null", "undefined", or similar placeholders, treat it as no cookie
    if cleaned_val.lower() in ["", "none", "null", "undefined"]:
        return []
    return [
        {
            "name": "li_at",
            "value": cleaned_val,
            "domain": ".linkedin.com",
            "path": "/",
            "expires": time.time() + 3600 * 24 * 30, # 30 days
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        }
    ]

# Learning Comment: On Windows, web servers like Uvicorn use the SelectorEventLoop
# which does not support running subprocesses (which Playwright needs to control Chromium).
# To bypass this restriction, we run Playwright inside a separate background thread 
# and explicitly set the loop policy to ProactorEventLoop policy for that thread only.
def _run_in_thread(func, *args, **kwargs):
    """
    Run a scraping function in a new thread with a ProactorEventLoop.
    """
    q = Queue()
    
    def wrapper():
        if sys.platform == 'win32':
            import asyncio
            try:
                # Force Windows Proactor loop policy for this thread
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass
        try:
            res = func(*args, **kwargs)
            q.put((True, res))
        except Exception as e:
            import traceback
            q.put((False, (e, traceback.format_exc())))
            
    t = threading.Thread(target=wrapper)
    t.start()
    t.join()
    
    success, val = q.get()
    if success:
        return val
    else:
        exc, tb = val
        raise RuntimeError(f"Error in scraper thread: {exc}\n{tb}")

def normalize_linkedin_url(url: str) -> str:
    """
    Safely normalize any raw LinkedIn job URL string into a clean canonical URL:
    https://www.linkedin.com/jobs/view/<job_slug_or_id>/
    Prevents malformed domain concatenation bugs (e.g., https://www.linkedin.comwww.linkedin.com).
    """
    if not url:
        return "https://www.linkedin.com"
        
    url = url.strip("'\" ")
    
    # Extract currentJobId if present in query parameters
    if "currentJobId" in url:
        target_url = url if url.startswith("http") else f"https://{url}"
        parsed = urllib.parse.urlparse(target_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        if "currentJobId" in query_params and query_params["currentJobId"]:
            job_id = query_params["currentJobId"][0]
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
            
    # Ensure URL scheme
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
        
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    
    # Strip any duplicate hostname prefixes embedded inside the path
    while path.startswith("/www.linkedin.com") or path.startswith("www.linkedin.com"):
        if path.startswith("/www.linkedin.com"):
            path = path[len("/www.linkedin.com"):]
        elif path.startswith("www.linkedin.com"):
            path = path[len("www.linkedin.com"):]
            
    if not path.startswith("/"):
        path = "/" + path
        
    return f"https://www.linkedin.com{path}"


def scrape_job_details(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    """
    Scrape job details from a specific LinkedIn job URL.
    Optionally logs in using the li_at cookie to view full descriptions.
    """
    return _run_in_thread(_scrape_job_details_inner, url, li_at_cookie)

def _scrape_job_details_inner(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    # Normalize URL cleanly
    clean_url = normalize_linkedin_url(url)
            
    result = {
        "url": clean_url,
        "title": "Unknown Job Title",
        "company": "Unknown Company",
        "location": "Unknown Location",
        "description": "",
        "easy_apply": False,
        "success": False,
        "error": None
    }
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = context.new_page()
        
        fallback_triggered = False
        try:
            page.set_default_timeout(15000)
            try:
                page.goto(clean_url)
            except Exception as goto_err:
                # If navigation fails due to too many redirects and a cookie was used,
                # the cookie is likely invalid or expired. Fall back to a clean context.
                if "ERR_TOO_MANY_REDIRECTS" in str(goto_err) and li_at_cookie:
                    fallback_triggered = True
                    page.close()
                    context.close()
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    page.goto(clean_url)
                else:
                    raise goto_err
            
            page.wait_for_load_state("domcontentloaded")
            
            if li_at_cookie and not fallback_triggered:
                page.wait_for_timeout(2000)
                
            # Extract Job Title
            title_selectors = [
                ".job-details-jobs-unified-top-card__job-title",
                ".top-card-layout__title",
                ".topcard__title",
                "h1",
                "h2"
            ]
            for selector in title_selectors:
                el = page.locator(selector).first
                if el.is_visible():
                    result["title"] = el.inner_text().strip()
                    break
                    
            # Extract Company Name
            company_selectors = [
                ".job-details-jobs-unified-top-card__company-name",
                ".job-details-jobs-unified-top-card__primary-description a",
                ".topcard__org-name-link",
                ".topcard__company-name",
                "a[href*='/company/']"
            ]
            for selector in company_selectors:
                el = page.locator(selector).first
                if el.is_visible():
                    result["company"] = el.inner_text().strip()
                    break
                    
            # Extract Location
            location_selectors = [
                ".job-details-jobs-unified-top-card__primary-description",
                ".topcard__flavor--bullet",
                ".jobs-unified-top-card__bullet",
                ".topcard__location"
            ]
            for selector in location_selectors:
                el = page.locator(selector).first
                if el.is_visible():
                    text = el.inner_text().strip()
                    if "·" in text:
                        parts = [p.strip() for p in text.split("·")]
                        result["location"] = parts[1] if len(parts) > 1 else text
                    else:
                        result["location"] = text
                    break

            # Check for Easy Apply button or label
            try:
                ea_btn = page.locator(
                    "button[data-control-name='jobdetails_topcard_inapply'], "
                    "button.jobs-apply-button:has-text('Easy Apply'), "
                    "button:has-text('Easy Apply'), "
                    ".jobs-apply-button"
                ).first
                if ea_btn and ea_btn.is_visible():
                    result["easy_apply"] = True
                else:
                    top_card = page.locator(".job-details-jobs-unified-top-card, .top-card-layout, .topcard").first
                    if top_card.is_visible() and "easy apply" in top_card.inner_text().lower():
                        result["easy_apply"] = True
            except Exception:
                pass

            # Dismiss blocking overlays/authwalls
            try:
                dismiss_btn = page.locator("button.modal__dismiss, button[aria-label='Dismiss'], button.contextual-sign-in-modal__modal-dismiss-btn").first
                if dismiss_btn.is_visible():
                    dismiss_btn.click(timeout=2000)
            except Exception:
                pass

            try:
                page.evaluate("""
                    document.querySelectorAll('.modal, .modal__overlay, .contextual-sign-in-modal, .authwall-modal, .top-level-modal-container').forEach(el => el.remove());
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = 'auto';
                    document.body.style.pointerEvents = 'auto';
                """)
            except Exception:
                pass

            # Expand description
            try:
                show_more_button = page.locator("button.show-more-less-html__button--more").first
                if show_more_button.is_visible():
                    try:
                        show_more_button.click(timeout=3000)
                    except Exception:
                        show_more_button.click(force=True, timeout=2000)
                    page.wait_for_timeout(500)
            except Exception:
                pass
                
            description_selectors = [
                "#job-details",
                ".jobs-description__content",
                ".description__text",
                ".show-more-less-html__markup",
                ".jobs-box__html-content"
            ]
            for selector in description_selectors:
                el = page.locator(selector).first
                if el.is_visible():
                    result["description"] = el.inner_text().strip()
                    break
            
            if not result["description"]:
                body_text = page.locator("body").inner_text()
                if "Description" in body_text:
                    parts = body_text.split("Description", 1)
                    result["description"] = parts[1][:4000].strip()
            
            if result["description"]:
                result["success"] = True
            else:
                result["error"] = "Could not locate job description content on page."
                
        except Exception as e:
            result["error"] = str(e)
        finally:
            browser.close()
            
    return result

def search_linkedin_jobs(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for jobs on LinkedIn based on keywords and location.
    """
    return _run_in_thread(_search_linkedin_jobs_inner, keywords, location, limit, li_at_cookie)

def _search_linkedin_jobs_inner(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    jobs = []
    
    # URL encode parameters
    kw_encoded = urllib.parse.quote(keywords)
    loc_encoded = urllib.parse.quote(location)
    
    if li_at_cookie:
        url = f"https://www.linkedin.com/jobs/search/?keywords={kw_encoded}&location={loc_encoded}"
    else:
        url = f"https://www.linkedin.com/jobs/search?keywords={kw_encoded}&location={loc_encoded}"
        
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = context.new_page()
        
        fallback_triggered = False
        try:
            page.set_default_timeout(20000)
            try:
                page.goto(url)
            except Exception as goto_err:
                # Fall back to clean context if invalid cookie causes redirect loop
                if "ERR_TOO_MANY_REDIRECTS" in str(goto_err) and li_at_cookie:
                    fallback_triggered = True
                    page.close()
                    context.close()
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    page.goto(url)
                else:
                    raise goto_err
            
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)
            
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
                
            card_selectors = [
                ".scaffold-layout__list-item",
                ".job-card-container",
                ".jobs-search-results-list__list-item",
                ".base-card",
                ".base-search-card",
                ".jobs-search__results-list li",
                "li.job-search-card"
            ]
            cards = None
            for sel in card_selectors:
                found = page.locator(sel)
                if found.count() > 0:
                    cards = found
                    break

            if cards:
                count = min(cards.count(), limit)
                for i in range(count):
                    try:
                        card = cards.nth(i)

                        # Extract Title (check all possible title selectors)
                        title = "Unknown Title"
                        for t_sel in [".job-card-list__title", ".base-search-card__title", "a[class*='job-card']", "h3", "h4"]:
                            t_el = card.locator(t_sel).first
                            if t_el.is_visible():
                                txt = t_el.inner_text().strip()
                                if txt:
                                    title = txt
                                    break

                        # Extract Company (check all possible company selectors)
                        company = "Unknown Company"
                        for c_sel in [".job-card-container__primary-description", ".job-card-container__company-name", ".base-search-card__subtitle", "a[href*='/company/']"]:
                            c_el = card.locator(c_sel).first
                            if c_el.is_visible():
                                txt = c_el.inner_text().strip()
                                if txt:
                                    company = txt
                                    break

                        # Extract Location (check all possible location selectors)
                        loc = "Unknown Location"
                        for l_sel in [".job-card-container__metadata-item", ".job-search-card__location"]:
                            l_el = card.locator(l_sel).first
                            if l_el.is_visible():
                                txt = l_el.inner_text().strip()
                                if txt:
                                    loc = txt
                                    break

                        # Extract Link URL
                        href = ""
                        for a_idx in range(card.locator("a").count()):
                            a_el = card.locator("a").nth(a_idx)
                            h_val = a_el.get_attribute("href") or ""
                            if "/jobs/view/" in h_val or "currentJobId" in h_val:
                                href = h_val
                                break
                        if not href:
                            link_el = card.locator("a.base-card__full-link, a").first
                            if link_el.is_visible():
                                href = link_el.get_attribute("href") or ""

                        if href:
                            href = normalize_linkedin_url(href)

                        # Check Easy Apply
                        is_easy_apply = False
                        try:
                            card_text = card.inner_text().lower()
                            if "easy apply" in card_text or card.locator(".job-card-container__apply-method, .job-search-card__easy-apply-label, .easy-apply-label, span:has-text('Easy Apply'), button:has-text('Easy Apply')").count() > 0:
                                is_easy_apply = True
                        except Exception:
                            pass

                        if href and title != "Unknown Title":
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href,
                                "easy_apply": is_easy_apply
                            })
                    except Exception:
                        continue
                    except Exception:
                        continue
                        
        except Exception:
            pass
        finally:
            browser.close()
            
    return jobs
