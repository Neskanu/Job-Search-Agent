import time
import urllib.parse
from typing import List, Dict, Any, Optional
# Import the asynchronous Playwright API
from playwright.async_api import async_playwright

def prepare_cookies(li_at_value: str) -> List[Dict[str, Any]]:
    """
    Prepare LinkedIn session cookies for injection.
    This remains synchronous as it's a simple dictionary manipulation.
    """
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

# FastAPI Concept: Asynchronous functions ('async def') allow the server to pause 
# execution of this task while waiting for network/browser I/O, freeing up the thread 
# to handle other client requests in the meantime.
async def scrape_job_details(url: str, li_at_cookie: Optional[str] = None) -> Dict[str, Any]:
    """
    Asynchronously scrape job details from a specific LinkedIn job URL.
    Optionally logs in using the li_at cookie to view full descriptions.
    """
    # Normalize URL (clean up tracking query parameters)
    parsed_url = urllib.parse.urlparse(url)
    clean_url = f"https://www.linkedin.com{parsed_url.path}"
    if "currentJobId" in parsed_url.query:
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
    
    # We use 'async with' to manage the Playwright context asynchronously
    async with async_playwright() as p:
        # Launch browser headlessly
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            await context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = await context.new_page()
        
        try:
            # Set default timeout to 15 seconds (15000ms)
            page.set_default_timeout(15000)
            await page.goto(clean_url)
            
            # Wait for content to load
            await page.wait_for_load_state("domcontentloaded")
            
            # If logged in, wait briefly for dynamic segments to load
            if li_at_cookie:
                await page.wait_for_timeout(2000)
                
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
                if await el.is_visible():
                    result["title"] = (await el.inner_text()).strip()
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
                if await el.is_visible():
                    result["company"] = (await el.inner_text()).strip()
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
                if await el.is_visible():
                    text = (await el.inner_text()).strip()
                    if "·" in text:
                        parts = [p.strip() for p in text.split("·")]
                        result["location"] = parts[1] if len(parts) > 1 else text
                    else:
                        result["location"] = text
                    break

            # Dismiss blocking overlays/authwalls
            try:
                dismiss_btn = page.locator("button.modal__dismiss, button[aria-label='Dismiss'], button.contextual-sign-in-modal__modal-dismiss-btn").first
                if await dismiss_btn.is_visible():
                    await dismiss_btn.click(timeout=2000)
            except Exception:
                pass

            try:
                # Remove auth banners and overlays via JS execution
                await page.evaluate("""
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
                if await show_more_button.is_visible():
                    try:
                        await show_more_button.click(timeout=3000)
                    except Exception:
                        await show_more_button.click(force=True, timeout=2000)
                    await page.wait_for_timeout(500)
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
                if await el.is_visible():
                    result["description"] = (await el.inner_text()).strip()
                    break
            
            # Text fallback if selectors fail
            if not result["description"]:
                body_text = await page.locator("body").inner_text()
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
            await browser.close()
            
    return result

async def search_linkedin_jobs(keywords: str, location: str, limit: int = 10, li_at_cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Asynchronously search for jobs on LinkedIn based on keywords and location.
    """
    jobs = []
    
    # URL encode parameters
    kw_encoded = urllib.parse.quote(keywords)
    loc_encoded = urllib.parse.quote(location)
    
    if li_at_cookie:
        url = f"https://www.linkedin.com/jobs/search/?keywords={kw_encoded}&location={loc_encoded}"
    else:
        url = f"https://www.linkedin.com/jobs/search?keywords={kw_encoded}&location={loc_encoded}"
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        if li_at_cookie:
            await context.add_cookies(prepare_cookies(li_at_cookie))
            
        page = await context.new_page()
        page.set_default_timeout(20000)
        
        try:
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)
            
            # Scroll down to trigger listing loads
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                
            # Scrape listings (authenticated route)
            if li_at_cookie:
                card_selectors = [
                    ".scaffold-layout__list-item",
                    ".job-card-container",
                    ".jobs-search-results-list__list-item"
                ]
                cards = None
                for sel in card_selectors:
                    found = page.locator(sel)
                    if await found.count() > 0:
                        cards = found
                        break
                        
                card_count = await cards.count() if cards else 0
                count = min(card_count, limit)
                for i in range(count):
                    try:
                        card = cards.nth(i)
                        
                        # Get title
                        title_el = card.locator(".job-card-list__title").first
                        if not await title_el.is_visible():
                            title_el = card.locator("a[class*='job-card']").first
                            
                        title = (await title_el.inner_text()).strip() if await title_el.is_visible() else "Unknown Title"
                        
                        # Get URL link
                        href = ""
                        links = card.locator("a")
                        links_count = await links.count()
                        for j in range(links_count):
                            temp_el = links.nth(j)
                            href_val = await temp_el.get_attribute("href")
                            if href_val and "/jobs/view/" in href_val:
                                href = href_val
                                break
                        
                        if href and not href.startswith("http"):
                            href = "https://www.linkedin.com" + href
                            
                        if href:
                            parsed = urllib.parse.urlparse(href)
                            href = f"https://www.linkedin.com{parsed.path}"
                            
                        # Get company
                        company_el = card.locator(".job-card-container__primary-description").first
                        if not await company_el.is_visible():
                            company_el = card.locator(".job-card-container__company-name").first
                        company = (await company_el.inner_text()).strip() if await company_el.is_visible() else "Unknown Company"
                        
                        # Get location
                        loc_el = card.locator(".job-card-container__metadata-item").first
                        loc = (await loc_el.inner_text()).strip() if await loc_el.is_visible() else "Unknown Location"
                        
                        if href:
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href
                            })
                    except Exception:
                        continue
            # Scrape listings (public route)
            else:
                card_selectors = [
                    ".base-card",
                    ".base-search-card",
                    ".jobs-search__results-list li"
                ]
                cards = None
                for sel in card_selectors:
                    found = page.locator(sel)
                    if await found.count() > 0:
                        cards = found
                        break
                        
                card_count = await cards.count() if cards else 0
                count = min(card_count, limit)
                for i in range(count):
                    try:
                        card = cards.nth(i)
                        
                        title_el = card.locator(".base-search-card__title").first
                        title = (await title_el.inner_text()).strip() if await title_el.is_visible() else "Unknown Title"
                        
                        company_el = card.locator(".base-search-card__subtitle").first
                        company = (await company_el.inner_text()).strip() if await company_el.is_visible() else "Unknown Company"
                        
                        loc_el = card.locator(".job-search-card__location").first
                        loc = (await loc_el.inner_text()).strip() if await loc_el.is_visible() else "Unknown Location"
                        
                        link_el = card.locator("a.base-card__full-link").first
                        if not await link_el.is_visible():
                            link_el = card.locator("a").first
                        href = await link_el.get_attribute("href") if await link_el.is_visible() else ""
                        
                        if href:
                            parsed = urllib.parse.urlparse(href)
                            href = f"https://www.linkedin.com{parsed.path}"
                            
                            jobs.append({
                                "title": title,
                                "company": company,
                                "location": loc,
                                "url": href
                            })
                    except Exception:
                        continue
                        
        except Exception:
            pass
        finally:
            await browser.close()
            
    return jobs
