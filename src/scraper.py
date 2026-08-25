"""
src/scraper.py - Dual-Engine LinkedIn Job Scraper & Parser

Uses LinkedIn Guest API search endpoint as primary search engine to avoid 302 redirect loops,
authwall blocks, and missing results.
"""

import time
import urllib.parse
import sys
import threading
from queue import Queue
from typing import List, Dict, Any, Optional

from playwright.sync_api import sync_playwright
from src.browser_manager import prepare_linkedin_cookies, run_in_proactor_thread, cleanup_profile_locks, create_browser_context


def normalize_linkedin_url(url: str) -> str:
    """
    Safely normalize any raw LinkedIn job URL string into a clean canonical URL:
    https://www.linkedin.com/jobs/view/<job_slug_or_id>/
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

    # Strip duplicate hostname prefixes
    while path.startswith("/www.linkedin.com") or path.startswith("www.linkedin.com"):
        if path.startswith("/www.linkedin.com"):
            path = path[len("/www.linkedin.com"):]
        elif path.startswith("www.linkedin.com"):
            path = path[len("www.linkedin.com"):]

    if not path.startswith("/"):
        path = "/" + path

    return f"https://www.linkedin.com{path}"


def scrape_job_details(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    """Scrape job details from a specific LinkedIn job URL."""
    return run_in_proactor_thread(_scrape_job_details_inner, url, li_at_cookie)


def _scrape_job_details_inner(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        if li_at_cookie and li_at_cookie.lower() not in ("none", "null", "undefined"):
            try:
                context.add_cookies(prepare_linkedin_cookies(li_at_cookie))
            except Exception as e:
                print(f"[scraper] Failed to add LinkedIn cookies: {e}")
                pass

        page = context.new_page()

        try:
            page.set_default_timeout(20000)
            try:
                page.goto(clean_url, wait_until="domcontentloaded")
            except Exception as goto_err:
                if "ERR_TOO_MANY_REDIRECTS" in str(goto_err):
                    page.context.clear_cookies()
                    page.goto(clean_url, wait_until="domcontentloaded")
                else:
                    raise goto_err

            time.sleep(2.0)

            # Extract Title
            title_selectors = [
                ".job-details-jobs-unified-top-card__job-title",
                ".top-card-layout__title",
                ".topcard__title",
                "h1", "h2"
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

            # Check Easy Apply strictly
            try:
                ea_btn = page.locator(
                    "button[data-control-name='jobdetails_topcard_inapply'], "
                    "button.jobs-apply-button:has-text('Easy Apply'), "
                    "button:has-text('Easy Apply'), "
                    "a:has-text('Easy Apply'), "
                    ".job-search-card__easy-apply-label, "
                    "span:has-text('Easy Apply')"
                ).first
                if ea_btn and ea_btn.is_visible():
                    result["easy_apply"] = True
            except Exception as ea_err:
                print(f"[scraper] Note while checking Easy Apply locator: {ea_err}")
                pass

            # Expand description
            try:
                show_more_button = page.locator("button.show-more-less-html__button--more").first
                if show_more_button.is_visible():
                    try:
                        show_more_button.click(timeout=3000)
                    except Exception as click_err:
                        print(f"[scraper] Standard click on 'Show more' failed ({click_err}), trying force click...")
                        show_more_button.click(force=True, timeout=2000)
                    time.sleep(0.5)
            except Exception as exp_err:
                print(f"[scraper] Note while expanding job description: {exp_err}")
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
            try:
                browser.close()
            except Exception as close_err:
                print(f"[scraper] Failed to close browser cleanly: {close_err}")
                pass

    return result


def search_linkedin_jobs(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search for jobs on LinkedIn using dual-engine search strategy."""
    return run_in_proactor_thread(_search_linkedin_jobs_inner, keywords, location, limit, li_at_cookie)


def _search_linkedin_jobs_inner(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    jobs = []
    seen_urls = set()
    kw_encoded = urllib.parse.quote(keywords)
    loc_encoded = urllib.parse.quote(location)

    # Engine 1: Guest API endpoint (Fast, structured, no 302 redirect loops or authwalls)
    api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={kw_encoded}&location={loc_encoded}&start=0"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"[scraper] Fetching job search via Guest API -> {api_url}")
            page.goto(api_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(1.5)

            cards = page.locator("li.job-search-card, div.job-search-card")
            if cards.count() == 0:
                cards = page.locator("li")

            count = cards.count()
            if count > 0:
                for i in range(count):
                    if len(jobs) >= limit:
                        break
                    try:
                        card = cards.nth(i)
                        
                        # Title
                        title = "Unknown Title"
                        for t_sel in [".base-search-card__title", ".job-search-card__title", "h3", "h4"]:
                            t_el = card.locator(t_sel).first
                            if t_el.is_visible():
                                txt = t_el.inner_text().strip()
                                if txt:
                                    title = txt
                                    break

                        # Company
                        company = "Unknown Company"
                        for c_sel in [".base-search-card__subtitle", ".job-search-card__subtitle", "a[href*='/company/']"]:
                            c_el = card.locator(c_sel).first
                            if c_el.is_visible():
                                txt = c_el.inner_text().strip()
                                if txt:
                                    company = txt
                                    break

                        # Location
                        loc = "Unknown Location"
                        for l_sel in [".job-search-card__location", ".base-search-card__metadata"]:
                            l_el = card.locator(l_sel).first
                            if l_el.is_visible():
                                txt = l_el.inner_text().strip()
                                if txt:
                                    loc = txt
                                    break

                        # Link URL
                        href = ""
                        link_el = card.locator("a.base-card__full-link, a").first
                        if link_el.is_visible():
                            href = link_el.get_attribute("href") or ""
                        if href:
                            href = normalize_linkedin_url(href)

                        # Easy Apply check
                        is_easy = False
                        try:
                            card_text = card.inner_text().lower()
                            if "easy apply" in card_text or card.locator(".job-search-card__easy-apply-label, span:has-text('Easy Apply')").count() > 0:
                                is_easy = True
                        except Exception as ea_card_err:
                            print(f"[scraper] Note while checking guest API card Easy Apply: {ea_card_err}")
                            pass

                        if href and title != "Unknown Title" and href not in seen_urls:
                            seen_urls.add(href)
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href,
                                "easy_apply": is_easy
                            })
                    except Exception as card_err:
                        print(f"[scraper] Note parsing guest API job card: {card_err}")
                        continue
        except Exception as api_err:
            print(f"[scraper] Guest API search note: {api_err}")
        finally:
            try:
                browser.close()
            except Exception as close_err:
                print(f"[scraper] Failed to close Guest API browser cleanly: {close_err}")
                pass

    if jobs:
        print(f"[scraper] Successfully scraped {len(jobs)} unique jobs via Guest API.")
        return jobs

    # Engine 2: Fallback to standard web search if API returns empty
    print("[scraper] Falling back to standard browser search...")
    search_url = f"https://www.linkedin.com/jobs/search?keywords={kw_encoded}&location={loc_encoded}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2.0)

            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)

            cards = page.locator("li.job-search-card, div.job-search-card")
            if cards.count() == 0:
                cards = page.locator(".base-card, .base-search-card")

            if cards.count() > 0:
                for i in range(cards.count()):
                    if len(jobs) >= limit:
                        break
                    try:
                        card = cards.nth(i)
                        title_el = card.locator(".base-search-card__title, h3").first
                        title = title_el.inner_text().strip() if title_el.is_visible() else "Unknown Title"

                        comp_el = card.locator(".base-search-card__subtitle, a[href*='/company/']").first
                        company = comp_el.inner_text().strip() if comp_el.is_visible() else "Unknown Company"

                        loc_el = card.locator(".job-search-card__location").first
                        loc = loc_el.inner_text().strip() if loc_el.is_visible() else "Unknown Location"

                        link_el = card.locator("a.base-card__full-link, a").first
                        href = link_el.get_attribute("href") if link_el.is_visible() else ""
                        if href:
                            href = normalize_linkedin_url(href)

                        is_easy = False
                        try:
                            if "easy apply" in card.inner_text().lower():
                                is_easy = True
                        except Exception as fb_ea_err:
                            print(f"[scraper] Note while checking fallback card Easy Apply: {fb_ea_err}")
                            pass

                        if href and title != "Unknown Title" and href not in seen_urls:
                            seen_urls.add(href)
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href,
                                "easy_apply": is_easy
                            })
                    except Exception as fb_card_err:
                        print(f"[scraper] Note parsing fallback job card: {fb_card_err}")
                        continue
        except Exception as fb_err:
            print(f"[scraper] Fallback search error: {fb_err}")
        finally:
            try:
                browser.close()
            except Exception as close_err:
                print(f"[scraper] Failed to close fallback browser cleanly: {close_err}")
                pass

    return jobs
