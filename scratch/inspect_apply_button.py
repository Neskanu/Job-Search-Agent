import time
from playwright.sync_api import sync_playwright

url = "https://www.linkedin.com/jobs/view/senior-instructional-designer-contract-remote-at-infuse-4428896501"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    time.sleep(2.0)
    
    # Print buttons & apply links
    elements = page.query_selector_all("a, button")
    print(f"Total links/buttons found: {len(elements)}")
    for el in elements:
        try:
            txt = el.inner_text().strip()
            href = el.get_attribute("href") or ""
            cls = el.get_attribute("class") or ""
            if "apply" in txt.lower() or "apply" in href.lower() or "apply" in cls.lower():
                print(f"MATCH: Tag={el.evaluate('e => e.tagName')} Text='{txt}' Class='{cls}' Href='{href}'")
        except Exception as e:
            print(f"[inspect_apply_button] Error evaluating element: {e}")
            pass
    browser.close()
