# app/quiz_solver.py
import os
import json
import re
import time
import base64
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
import pandas as pd
import pdfplumber
from io import StringIO

from .browser import fetch_page
from .config import settings
from .llm_client import ask_llm_for_answer


def _find_submit_url(
    page_url: str,
    page_text: str,
    html: str,
    links: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Try to infer the "submit" URL from multiple hints.

    We consider, in order:
      1. Lines like: 'POST this JSON to https://example.com/submit'
      2. Any line starting with 'POST ... https://...'
      3. Lines like: 'Post your answer to https://example.com/...'
      4. Any https URL that contains 'submit'
      5. Any '/...submit...' relative path in text or HTML attributes
      6. Any <a href="..."> link whose href contains 'submit'
      7. data-submit-url="..." or similar attributes in the raw HTML
      8. As a last fallback, if there's exactly one https URL in the text, return it
    """
    # 1) Highest-priority: explicit "POST ... https://..." instruction
    m_post_url = re.search(r"\bPOST\b[^\n\r]*?(https?://\S+)", page_text or "", re.IGNORECASE)
    if m_post_url:
        url = m_post_url.group(1).strip().strip('",')
        return url

    # 2) Text like: 'Post your answer to https://...' or 'submit your answer to ...'
    lines = (page_text or "").splitlines()
    for line in lines:
        lower = line.lower()
        if "post your answer to" in lower or "submit your answer to" in lower:
            match = re.search(r"https?://\S+", line)
            if match:
                return match.group(0).strip()

    # 3) Any https URL in the text containing 'submit'
    all_matches = re.findall(r"https?://\S+", page_text or "")
    for url in all_matches:
        if "submit" in url.lower():
            return url.strip()

    # 4) Check raw HTML for data-* attributes (e.g. data-submit-url)
    m_data_submit = re.search(r'data-submit-url=["\']([^"\']+)["\']', html or "", re.IGNORECASE)
    if m_data_submit:
        path = m_data_submit.group(1).strip()
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(page_url, path)

    # 5) Any '/...submit...' path in the text
    m_rel = re.search(r"(/[^ \t\r\n\"']*submit[^ \t\r\n\"']*)", page_text or "")
    if m_rel:
        path = m_rel.group(1).strip().strip('",')
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(page_url, path)

    # 6) Look through parsed links (<a href="...">) for anything with 'submit'
    for link in links or []:
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if "submit" in href.lower():
            if href.startswith("http://") or href.startswith("https://"):
                return href
            return urljoin(page_url, href)

    # 7) As an extreme fallback, if there's exactly one https URL total, and nothing else
    if len(all_matches) == 1:
        return all_matches[0].strip()

    return None


def _decode_atob_blocks(html: str) -> str:
    """
    Find JavaScript atob(`...`) calls in the HTML, base64-decode their content,
    and return the concatenated decoded text (if any).
    """
    matches = re.findall(r"atob\(\s*`([^`]+)`\s*\)", html or "")
    decoded_parts: List[str] = []
    for m in matches:
        b64 = "".join(m.split())
        try:
            decoded_bytes = base64.b64decode(b64)
            decoded_text = decoded_bytes.decode("utf-8", errors="replace")
            decoded_parts.append(decoded_text)
        except Exception:
            continue
    return "\n\n".join(decoded_parts)


async def _download_resource_text(
    client: httpx.AsyncClient, url: str
) -> Tuple[str, str]:
    """
    Download a remote resource and return (description, content_as_text).
    Handles csv, excel, json, txt, pdf; otherwise returns a binary note.
    """
    resp = await client.get(url, timeout=60)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    lower_url = url.lower()

    def limit_text(txt: str, max_chars: int = 4000) -> str:
        if len(txt) > max_chars:
            return txt[:max_chars] + "\n...[truncated]..."
        return txt

    # CSV
    if lower_url.endswith(".csv") or "text/csv" in content_type:
        df = pd.read_csv(StringIO(resp.text))
        return (f"CSV file from {url}", limit_text(df.to_csv(index=False)))

    # Excel
    if lower_url.endswith((".xlsx", ".xls")):
        from io import BytesIO
        excel_file = BytesIO(resp.content)
        df = pd.read_excel(excel_file)
        return (f"Excel file from {url}", limit_text(df.to_csv(index=False)))

    # JSON
    if lower_url.endswith(".json") or "application/json" in content_type:
        try:
            obj = resp.json()
            text = json.dumps(obj, indent=2)
            return (f"JSON file from {url}", limit_text(text))
        except Exception:
            return (f"JSON-like file from {url}", limit_text(resp.text))

    # Plain text
    if lower_url.endswith(".txt") or "text/plain" in content_type:
        return (f"Text file from {url}", limit_text(resp.text))

    # PDF
    if lower_url.endswith(".pdf") or "application/pdf" in content_type:
        from io import BytesIO
        pdf_file = BytesIO(resp.content)
        text_parts: List[str] = []
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n\n".join(text_parts)
        return (f"PDF file from {url}", limit_text(text))

    return (f"Binary/unknown file from {url} (content-type={content_type})", "[binary content not shown]")


def _heuristic_extract_answer(page_text: str) -> Optional[Any]:
    """
    Improved heuristics to extract answers from page text.

    Tries these in order (and returns the first plausible result):
    1. JSON-like `"answer": <value>` or 'answer' = <value> (handles quoted strings, numbers, true/false)
    2. Quoted string patterns: "the answer is '...'" or Answer: "..."
    3. Lines starting with 'Answer:' or 'The answer is' grabbing the rest of the line (words allowed)
    4. Bare words enclosed in quotes (single or double) - but filter out short page titles
    5. First standalone number (float or int)
    6. First non-empty line (as last resort)
    Returns int/float where possible, otherwise returns a stripped string.
    """
    if not page_text:
        return None

    txt = page_text.strip()

    # 1) JSON-like: "answer": <value>  or 'answer' : <value>
    m_json = re.search(r'"?answer"?\s*[:=]\s*(true|false|null|[+-]?\d*\.\d+|[+-]?\d+|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')', txt, re.IGNORECASE)
    if m_json:
        raw = m_json.group(1).strip()
        low = raw.lower()
        if low == "null":
            return None
        if low == "true":
            return True
        if low == "false":
            return False
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            return raw[1:-1].strip()
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except Exception:
            return raw

    # 2) Quoted answer forms: Answer: "something"
    m_quoted = re.search(r'(?:answer[:\s]|the answer (?:is|=)\s*)["\']([^"\']{1,500})["\']', txt, re.IGNORECASE)
    if m_quoted:
        return m_quoted.group(1).strip()

    # 3) Lines like "Answer: something" (word answer allowed)
    m_line = re.search(r'(?m)^[ \t\-]*Answer[:\s]+\s*(.{1,500})$', txt, re.IGNORECASE)
    if m_line:
        candidate = m_line.group(1).strip()
        return candidate.strip(' .;,"\'\n\r\t')

    m_line2 = re.search(r'(?:the answer (?:is|=)\s*)([A-Za-z0-9 _\-\(\)\[\]\.]{1,500})', txt, re.IGNORECASE)
    if m_line2:
        return m_line2.group(1).strip().strip(' .;,"\'\n\r\t')

    # 4) Any quoted token anywhere (first occurrence) - but skip very short page-title-like answers
    m_anyquote = re.search(r'["\']([^"\']{1,500})["\']', txt)
    if m_anyquote:
        candidate = m_anyquote.group(1).strip()
        # Filter: if it looks like a page title (short, all caps or title case, contains "demo" or "page")
        # it's probably not the answer to a quiz question
        if not (len(candidate) < 30 and ("demo" in candidate.lower() or "page" in candidate.lower())):
            return candidate

    # 5) Any standalone number (float or int)
    m_num = re.search(r'([-+]?\d*\.\d+|\d+)', txt)
    if m_num:
        num = m_num.group(1)
        try:
            if '.' in num:
                return float(num)
            return int(num)
        except Exception:
            return num

    # 6) As a last resort, the first non-empty line
    for line in txt.splitlines():
        s = line.strip()
        if s:
            return s[:500]

    return None


async def _build_quiz_context(
    url: str, html: str, page_text: str, links: List[Dict[str, Any]]
) -> str:
    """
    Build a textual context to send to the LLM (page url, text, and sampled resources).
    """
    ctx_parts: List[str] = []
    ctx_parts.append(f"Quiz page URL: {url}\n")
    ctx_parts.append("Visible page text:\n")
    ctx_parts.append((page_text or "").strip())

    # Identify possible data links
    data_links: List[str] = []
    for link in links or []:
        href = (link.get("href") or "").strip()
        if not href:
            continue
        href_lower = href.lower()
        if any(href_lower.endswith(ext) for ext in (".csv", ".xlsx", ".xls", ".json", ".txt", ".pdf")):
            data_links.append(href)

    data_links = list(dict.fromkeys(data_links))[:3]

    if data_links:
        ctx_parts.append("\n\nDownloaded resources:\n")
        async with httpx.AsyncClient() as client:
            for dl in data_links:
                try:
                    desc, content_text = await _download_resource_text(client, dl)
                    ctx_parts.append(f"\n--- {desc} ---\n")
                    ctx_parts.append(content_text)
                except Exception as e:
                    ctx_parts.append(f"\n--- Failed to download {dl}: {e!r} ---\n")

    return "\n".join(ctx_parts)


async def solve_quiz_chain(
    email: str,
    secret: str,
    start_url: str,
) -> Dict[str, Any]:
    """
    Solve one or more quiz URLs, following chain as long as server returns a next url.
    """
    start_time = time.monotonic()
    deadline = start_time + settings.max_quiz_duration_secs

    steps: List[Dict[str, Any]] = []
    current_url: Optional[str] = start_url

    async with httpx.AsyncClient() as client:
        while current_url is not None and time.monotonic() < deadline:
            step_info: Dict[str, Any] = {"url": current_url}
            try:
                # 1. Fetch page (playwright or httpx fallback)
                html, page_text, links = await fetch_page(current_url)

                # --- DEBUG: Capture what the solver actually sees on the page (zero-cost) ---
                step_info["page_text_snippet"] = (page_text or "")[:2000]
                step_info["decoded_snippet"] = ""
                try:
                    step_info["links_preview"] = [l.get("href") for l in (links or [])][:10]
                except Exception:
                    step_info["links_preview"] = []
                # ---------------------------------------------------------------------------

                # 1.5 decode any atob embedded content (and add links from it)
                decoded = _decode_atob_blocks(html)
                if decoded:
                    page_text = (page_text or "") + "\n\nDecoded atob content:\n" + decoded
                    step_info["decoded_snippet"] = decoded[:2000]
                    # extract links from decoded HTML if present
                    link_pattern = re.compile(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
                    extra_links: List[Dict[str, Any]] = []
                    for href, inner in link_pattern.findall(decoded):
                        clean_inner = re.sub(r"<[^>]+>", " ", inner)
                        clean_inner = re.sub(r"\s+", " ", clean_inner).strip()
                        extra_links.append({"href": href, "text": clean_inner})
                    if extra_links:
                        links = list(links or []) + extra_links

                # ------------------ Special-case: follow demo-scrape-data link ------------------
                # If the page instructs to "Scrape /demo-scrape-data..." or we have a link with that pattern,
                # follow it and try to extract the secret code locally (no LLM).
                scrape_target = None
                for link in (links or []):
                    href = (link.get("href") or "").strip()
                    if not href:
                        continue
                    if "demo-scrape-data" in href or "scrape-data" in href or "/demo-scrape" in href:
                        if href.startswith("http://") or href.startswith("https://"):
                            scrape_target = href
                        else:
                            scrape_target = urljoin(current_url, href)
                        break

                if not scrape_target:
                    m = re.search(r"(/[^ \n\r\t\"']*demo[-_]?scrape[^ \n\r\t\"']*)", page_text or "", re.IGNORECASE)
                    if m:
                        scrape_target = urljoin(current_url, m.group(1).strip().strip('",'))

                answer_obj = None  # may be set by special-case or by LLM
                if scrape_target:
                    step_info["followed_scrape_target"] = scrape_target
                    try:
                        scrape_html, scrape_text, scrape_links = await fetch_page(scrape_target)
                        scrape_decoded = _decode_atob_blocks(scrape_html)
                        combined_scrape_text = (scrape_text or "") + "\n\n" + (scrape_decoded or "")

                        # Heuristics for secret extraction
                        secret = None
                        m1 = re.search(r'"secret"\s*:\s*["\']([^"\']{4,200})["\']', combined_scrape_text, re.IGNORECASE)
                        if m1:
                            secret = m1.group(1).strip()

                        if not secret:
                            m2 = re.search(r'(?:secret code|secret|the secret is|secret:)\s*[:=]?\s*["\']?([A-Za-z0-9\-_=+]{3,200})["\']?', combined_scrape_text, re.IGNORECASE)
                            if m2:
                                secret = m2.group(1).strip()

                        if not secret:
                            m3 = re.search(r'([A-Za-z0-9+/=]{12,200})', combined_scrape_text)
                            if m3:
                                secret = m3.group(1).strip()

                        if secret:
                            answer_obj = {"answer": secret}
                            step_info["note"] = "Extracted secret locally from scrape target (no LLM used)."
                            step_info["extracted_secret_preview"] = secret[:200]
                        else:
                            step_info["note"] = "Followed scrape target but failed to extract secret locally."
                    except Exception as e:
                        step_info["follow_scrape_error"] = repr(e)
                # ---------------- end special-case ----------------------------------------------

                # 2. Build the LLM context (only used if we need the LLM)
                quiz_context = await _build_quiz_context(current_url, html, page_text, links or [])

                # 3. Ask LLM for the 'answer' only if special-case didn't produce one
                if not isinstance(answer_obj, dict) or answer_obj.get("answer", None) is None:
                    answer_obj = await ask_llm_for_answer(quiz_context)
                step_info["llm_answer_obj"] = answer_obj

                # Zero-cost fallback: if answer is None/null, try heuristics
                ans = answer_obj.get("answer", None) if isinstance(answer_obj, dict) else None
                if ans is None:
                    combined_text = (page_text or "") + "\n\n" + (decoded or "")
                    heuristic = _heuristic_extract_answer(combined_text)
                    if heuristic is not None:
                        answer_obj["answer"] = heuristic
                        step_info["llm_answer_obj"] = answer_obj
                        step_info["note"] = step_info.get("note", "") + " Heuristic fallback used (no LLM answer)."
                    else:
                        if os.getenv("ENABLE_LLM_RETRY", "false").lower() in ("1", "true", "yes"):
                            strict_context = (
                                "You MUST return only valid JSON with a single key named 'answer'. "
                                "If you cannot compute an answer, return {\"answer\": null} explicitly.\n\n"
                                + quiz_context
                            )
                            try:
                                retry_obj = await ask_llm_for_answer(strict_context)
                                step_info["retry_llm_answer_obj"] = retry_obj
                                if isinstance(retry_obj, dict) and retry_obj.get("answer", None) is not None:
                                    answer_obj = retry_obj
                                    step_info["llm_answer_obj"] = answer_obj
                                else:
                                    step_info["note"] = step_info.get("note", "") + " LLM retry returned null."
                            except Exception as e:
                                step_info["retry_error"] = repr(e)

                        if (not isinstance(answer_obj, dict)) or answer_obj.get("answer", None) is None:
                            heuristic2 = _heuristic_extract_answer(combined_text)
                            if heuristic2 is not None:
                                answer_obj["answer"] = heuristic2
                                step_info["llm_answer_obj"] = answer_obj
                                step_info["note"] = step_info.get("note", "") + " Heuristic fallback used after retry."
                            else:
                                raise RuntimeError("LLM returned null/empty answer and heuristics failed.")

                # 4. Determine submit URL using page_text, html, and links
                submit_url = _find_submit_url(page_url=current_url, page_text=page_text or "", html=html or "", links=links or [])

                # Extra fallback: look for any link whose href contains "submit"
                if not submit_url:
                    for link in (links or []):
                        href = (link.get("href") or "").strip()
                        if not href:
                            continue
                        if "submit" in href.lower():
                            if href.startswith("http://") or href.startswith("https://"):
                                submit_url = href
                            else:
                                submit_url = urljoin(current_url, href)
                            break

                if not submit_url:
                    raise RuntimeError("Could not find submit URL on the page.")
                step_info["submit_url"] = submit_url

                # 5. Build payload and submit
                submit_payload: Dict[str, Any] = {
                    "email": email,
                    "secret": secret,
                    "url": current_url,
                    "answer": answer_obj["answer"],
                }

                # Validate payload size (spec requires < 1MB)
                payload_json = json.dumps(submit_payload)
                payload_size = len(payload_json.encode('utf-8'))
                if payload_size > 1_000_000:
                    raise RuntimeError(
                        f"Payload size {payload_size} bytes exceeds 1MB limit. "
                        f"Answer may be too large."
                    )
                step_info["payload_size_bytes"] = payload_size

                resp = await client.post(submit_url, json=submit_payload, timeout=60)
                step_info["submit_status_code"] = resp.status_code
                try:
                    resp_json = resp.json()
                except json.JSONDecodeError:
                    resp_json = {"raw_text": resp.text}
                step_info["submit_response"] = resp_json

                # 6. Follow next URL if any
                next_url = resp_json.get("url")
                if isinstance(next_url, str) and next_url.strip():
                    current_url = next_url.strip()
                else:
                    current_url = None

            except Exception as e:
                import traceback
                tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                step_info["error"] = repr(e)
                step_info["traceback"] = tb_str
                current_url = None

            steps.append(step_info)

    total_time = time.monotonic() - start_time
    return {
        "steps": steps,
        "total_time_secs": total_time,
        "within_time_limit": total_time <= settings.max_quiz_duration_secs,
    }
