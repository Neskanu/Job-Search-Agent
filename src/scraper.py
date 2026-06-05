import time
import urllib.parse
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright

import sys
import threading
from queue import Queue

def prepare_cookies(li_at_value: str) -> List[Dict[str, Any]]:
    """Convert raw li_at cookie string to Playwright format."""
    if not li_at_value:
        return []
    return [
        {
            "name": "li_at",
            "value": li_at_value.strip(),
            "domain": ".linkedin.com",
            "path": "/",
            "expires": time.time() + 3600 * 24 * 30, # 30 days
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        }
    ]

def _run_in_thread(func, *args, **kwargs):
    """
    Run a function in a new thread. 
    Crucial on Windows with Streamlit/Tornado because the main thread 
    runs a SelectorEventLoop which does not support subprocesses (needed by Playwright).
    """
    q = Queue()
    
    def wrapper():
        if sys.platform == 'win32':
            import asyncio
            try:
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

def scrape_job_details(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    """
    Scrape job details from a specific LinkedIn job URL.
    Optionally logs in using the li_at cookie to view full descriptions.
    """
    return _run_in_thread(_scrape_job_details_inner, url, li_at_cookie)

def _scrape_job_details_inner(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    # Normalize URL (clean up tracking query parameters)
    parsed_url = urllib.parse.urlparse(url)
    clean_url = f"https://www.linkedin.com{parsed_url.path}"
    if "currentJobId" in parsed_url.query:
        # e.g., if url is linkedin.com/jobs/view/12345 or has currentJobId
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if "currentJobId" in query_params:
            job_id = query_params["currentJobId"][0]
            clean_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            
    result = {
        "url": clean_url,
        "title": "Unknown Job Title",
        "company": "Unknown Company",
        "location": "Unknown Location",
        "description": "",
        "success": False,
        "error": None
    }
    
    with sync_playwright() as p:
        # Launch browser in headless mode to run in background
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = context.new_page()
        
        try:
            # Set default timeout to 15 seconds
            page.set_default_timeout(15000)
            page.goto(clean_url)
            
            # Wait for content to load
            page.wait_for_load_state("domcontentloaded")
            
            # If we are logged in, wait a bit for dynamic elements
            if li_at_cookie:
                page.wait_for_timeout(2000)
                
            # Attempt to extract Job Title
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
                    
            # Attempt to extract Company Name
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
                    
            # Attempt to extract Location
            location_selectors = [
                ".job-details-jobs-unified-top-card__primary-description",
                ".topcard__flavor--bullet",
                ".jobs-unified-top-card__bullet",
                ".topcard__location"
            ]
            for selector in location_selectors:
                el = page.locator(selector).first
                if el.is_visible():
                    # For unified top card, it contains company, location, applicants, etc.
                    # We might need to split or clean it.
                    text = el.inner_text().strip()
                    if "·" in text:
                        parts = [p.strip() for p in text.split("·")]
                        if len(parts) > 1:
                            result["location"] = parts[1]
                        else:
                            result["location"] = text
                    else:
                        result["location"] = text
                    break

            # Dismiss sign-in modal or cookie overlays if they exist
            try:
                dismiss_btn = page.locator("button.modal__dismiss, button[aria-label='Dismiss'], button.contextual-sign-in-modal__modal-dismiss-btn").first
                if dismiss_btn.is_visible():
                    dismiss_btn.click(timeout=2000)
            except Exception:
                pass

            # Inject JS to clean the page from modal overlays and enable scrolling/interaction
            try:
                page.evaluate("""
                    document.querySelectorAll('.modal, .modal__overlay, .contextual-sign-in-modal, .authwall-modal, .top-level-modal-container').forEach(el => el.remove());
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = 'auto';
                    document.body.style.pointerEvents = 'auto';
                """)
            except Exception:
                pass

            # Attempt to extract Job Description
            # LinkedIn often hides the full text behind a "Show more" button if public
            try:
                show_more_button = page.locator("button.show-more-less-html__button--more").first
                if show_more_button.is_visible():
                    try:
                        show_more_button.click(timeout=3000)
                    except Exception:
                        # Try forcing the click if normal click is intercepted
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
                # Fallback to general page text if selectors failed but page loaded
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
    If li_at_cookie is provided, performs an authenticated search (recommended).
    Otherwise, uses the public search route.
    """
    return _run_in_thread(_search_linkedin_jobs_inner, keywords, location, limit, li_at_cookie)

def _search_linkedin_jobs_inner(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    jobs = []
    
    # URL encode parameters
    kw_encoded = urllib.parse.quote(keywords)
    loc_encoded = urllib.parse.quote(location)
    
    if li_at_cookie:
        # Authenticated search URL
        url = f"https://www.linkedin.com/jobs/search/?keywords={kw_encoded}&location={loc_encoded}"
    else:
        # Public search URL
        url = f"https://www.linkedin.com/jobs/search?keywords={kw_encoded}&location={loc_encoded}"
        
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = context.new_page()
        page.set_default_timeout(20000)
        
        try:
            page.goto(url)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000) # Wait for listings to render
            
            # Let's scroll down to load more jobs (especially for public page)
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
                
            # Locate job cards
            if li_at_cookie:
                # Selectors for authenticated view
                # Job cards are usually represented by .job-card-container or .scaffold-layout__list-item
                card_selectors = [
                    ".scaffold-layout__list-item",
                    ".job-card-container",
                    ".jobs-search-results-list__list-item"
                ]
                cards = []
                for sel in card_selectors:
                    found = page.locator(sel)
                    if found.count() > 0:
                        cards = found
                        break
                        
                count = min(cards.count() if cards else 0, limit)
                for i in range(count):
                    try:
                        card = cards.nth(i)
                        
                        # Get title
                        title_el = card.locator(".job-card-list__title").first
                        if not title_el.is_visible():
                            title_el = card.locator("a[class*='job-card']").first
                            
                        title = title_el.inner_text().strip() if title_el.is_visible() else "Unknown Title"
                        
                        # Get link
                        # Link is usually the href of the title element
                        href = ""
                        link_el = card.locator("a").first
                        for j in range(card.locator("a").count()):
                            temp_el = card.locator("a").nth(j)
                            href_val = temp_el.get_attribute("href")
                            if href_val and "/jobs/view/" in href_val:
                                href = href_val
                                break
                        
                        if href and not href.startswith("http"):
                            href = "https://www.linkedin.com" + href
                            
                        # Split query parameters from URL
                        if href:
                            parsed = urllib.parse.urlparse(href)
                            href = f"https://www.linkedin.com{parsed.path}"
                            
                        # Get company
                        company_el = card.locator(".job-card-container__primary-description").first
                        if not company_el.is_visible():
                            company_el = card.locator(".job-card-container__company-name").first
                        company = company_el.inner_text().strip() if company_el.is_visible() else "Unknown Company"
                        
                        # Get location
                        loc_el = card.locator(".job-card-container__metadata-item").first
                        loc = loc_el.inner_text().strip() if loc_el.is_visible() else "Unknown Location"
                        
                        if href:
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href
                            })
                    except Exception as card_err:
                        # Skip cards that throw errors while parsing
                        continue
            else:
                # Selectors for public view
                # Public job cards are usually .base-card, .base-search-card or similar
                card_selectors = [
                    ".base-card",
                    ".base-search-card",
                    ".jobs-search__results-list li"
                ]
                cards = []
                for sel in card_selectors:
                    found = page.locator(sel)
                    if found.count() > 0:
                        cards = found
                        break
                        
                count = min(cards.count() if cards else 0, limit)
                for i in range(count):
                    try:
                        card = cards.nth(i)
                        
                        title_el = card.locator(".base-search-card__title").first
                        title = title_el.inner_text().strip() if title_el.is_visible() else "Unknown Title"
                        
                        company_el = card.locator(".base-search-card__subtitle").first
                        company = company_el.inner_text().strip() if company_el.is_visible() else "Unknown Company"
                        
                        loc_el = card.locator(".job-search-card__location").first
                        loc = loc_el.inner_text().strip() if loc_el.is_visible() else "Unknown Location"
                        
                        link_el = card.locator("a.base-card__full-link").first
                        if not link_el.is_visible():
                            link_el = card.locator("a").first
                        href = link_el.get_attribute("href") if link_el.is_visible() else ""
                        
                        if href:
                            # Clean up tracking params
                            parsed = urllib.parse.urlparse(href)
                            href = f"https://www.linkedin.com{parsed.path}"
                            
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href
                            })
                    except Exception as card_err:
                        continue
                        
        except Exception as e:
            # Return empty or partial list on search failures
            pass
        finally:
            browser.close()
            
    return jobs
