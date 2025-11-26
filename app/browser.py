# app/browser.py
import asyncio
import re
from typing import List, Dict, Tuple

import httpx

# Playwright import is done inside the sync runner to avoid async import issues
# and to fail gracefully if Playwright isn't available.
# We run sync_playwright inside asyncio.to_thread so that it doesn't interact badly
# with uvicorn's event loop on Windows.
PLAYWRIGHT_RENDER_TIMEOUT = 30  # seconds


async def fetch_page(url: str) -> Tuple[str, str, List[Dict[str, str]]]:
    """
    Fetch a page and return (html, visible_text, links).
    - Try fast httpx GET first.
    - If result seems to require JS (empty body text, uses atob, or minimal content),
      render using Playwright synchronously inside a thread via asyncio.to_thread.
    """
    # common headers to look like a browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            resp = await client.get(url, follow_redirects=True)
            html = resp.text or ""
    except Exception as e:
        # If httpx fails, set html empty and try Playwright below
        html = ""

    # Try to extract visible text using a very simple heuristic:
    # remove scripts and styles, then collapse whitespace
    def extract_text_from_html(source_html: str) -> str:
        if not source_html:
            return ""
        try:
            # Strip script/style tags for quick visible text extraction
            no_scripts = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", source_html)
            # Remove HTML tags
            text = re.sub(r"(?is)<[^>]+>", " ", no_scripts)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return ""

    page_text = extract_text_from_html(html)

    # Heuristic: decide whether to use Playwright
    needs_js = False
    # If there's an explicit atob encoded block (likely JS builds innerHTML)
    if "atob(" in html:
        needs_js = True
    # If httpx returned empty text or only whitespace
    if not page_text:
        needs_js = True
    # If page HTML contains many <script> but no visible content
    script_count = len(re.findall(r"(?i)<script\b", html or ""))
    if script_count > 2 and len(page_text) < 50:
        needs_js = True

    links: List[Dict[str, str]] = []

    # If we think JS is not needed, extract links from the static HTML and return
    if not needs_js:
        # Extract <a href="..."> quickly
        hrefs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html or "", re.IGNORECASE)
        for h in hrefs:
            links.append({"href": h, "text": ""})
        return html, page_text, links

    # Otherwise, render with Playwright to execute JS and get real DOM
    # We use asyncio.to_thread to run sync_playwright safely
    try:
        rendered = await asyncio.wait_for(asyncio.to_thread(_render_with_playwright, url), timeout=PLAYWRIGHT_RENDER_TIMEOUT)
        # rendered is a dict with keys: html, text, links
        if rendered and isinstance(rendered, dict):
            return rendered.get("html", "") or "", rendered.get("text", "") or "", rendered.get("links", []) or []
    except asyncio.TimeoutError:
        # timeout - fall back to whatever we had from httpx
        return html, page_text, links
    except Exception:
        # any other error -> fall back
        return html, page_text, links

    return html, page_text, links


def _render_with_playwright(url: str) -> Dict:
    """
    Synchronous helper that runs Playwright (sync API) to render the page and extract
    HTML, visible text, and links. This is intended to be called via asyncio.to_thread.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        # Playwright not installed in environment or cannot be imported
        raise RuntimeError(f"Playwright import failed: {e!r}")

    result = {"html": "", "text": "", "links": []}

    try:
        with sync_playwright() as p:
            # Launch headless chromium
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # Use networkidle so single-page apps have time to render
            page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait for JavaScript rendering to complete
            # Multiple waits to ensure content is fully rendered
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            
            # Give JS frameworks time to render (Vue, React, Angular, etc.)
            try:
                page.wait_for_timeout(2000)  # Wait 2 seconds for framework rendering
            except Exception:
                pass
            
            # Wait for body to have actual content
            try:
                page.wait_for_selector("body", state="attached", timeout=5000)
            except Exception:
                pass
            
            # Grab rendered HTML and visible text (body innerText)
            html = page.content() or ""
            # Try innerText('body') for visible text; fallback to content-based strip
            try:
                body_text = page.inner_text("body")
            except Exception:
                # fallback naive extraction
                body_text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
                body_text = re.sub(r"(?is)<[^>]+>", " ", body_text)
                body_text = re.sub(r"\s+", " ", body_text).strip()

            # Extract links
            hrefs = []
            try:
                anchors = page.query_selector_all("a")
                for a in anchors:
                    try:
                        href = a.get_attribute("href") or ""
                    except Exception:
                        href = ""
                    hrefs.append({"href": href, "text": (a.inner_text() or "").strip()})
            except Exception:
                # Fallback to regex on html
                hrefs = [{"href": h, "text": ""} for h in re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html or "", re.IGNORECASE)]

            result["html"] = html
            result["text"] = body_text
            result["links"] = hrefs

            try:
                browser.close()
            except Exception:
                pass

    except Exception as e:
        # Rethrow so caller can handle and fallback
        raise RuntimeError(f"Playwright rendering failed: {e!r}")

    return result
