# S.C.O.U.T. Phase 2 — Full Skill Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the remaining 20 browser skills to archie_scraper, register them in SKILL_MAP, and verify the full 33-test suite passes.

**Architecture:** Every skill lives in `archie-scraper/skills/<name>.py`, implements `run(page, url, params, job_id) -> dict`, and returns `{data, screenshots, network_log, findings, auto_approve}`. Skills are registered in `job_worker.SKILL_MAP`. Tests live in `archie-scraper/tests/test_skills_phase2.py`.

**Tech Stack:** Python 3.11, Playwright 1.44, Pillow (screenshot_diff), standard library only for everything else. All on branch `feat/scout-phase2`.

---

## File Map

**Create — archie-scraper/skills/ (20 new files)**
```
multi_page_scrape.py     authenticated_fetch.py   search_scrape.py
site_change_monitor.py   pdf_extract.py           document_download.py
login_test.py            signup_flow.py           network_inspect.py
accessibility_check.py   seo_snapshot.py          broken_link_check.py
screenshot_diff.py       form_audit.py            competitor_snapshot.py
ancestry_research.py     crm_enrich.py            contact_harvest.py
social_profile_check.py  price_monitor.py
```

**Modify**
```
archie-scraper/job_worker.py      add 20 entries to SKILL_MAP
archie-scraper/tests/test_skills_phase2.py   new test file (20 tests)
```

---

## Task 1: Core Scraping — multi_page_scrape, authenticated_fetch, search_scrape

**Files:**
- Create: `archie-scraper/skills/multi_page_scrape.py`
- Create: `archie-scraper/skills/authenticated_fetch.py`
- Create: `archie-scraper/skills/search_scrape.py`
- Create: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Create branch**
```bash
cd /mnt/archie_brain && git checkout -b feat/scout-phase2
```

- [ ] **Step 2: Write failing tests**

Create `/mnt/archie_brain/archie-scraper/tests/test_skills_phase2.py`:

```python
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch, call


def _page(texts=None, title="Test"):
    page = MagicMock()
    page.title.return_value = title
    page.goto.return_value = None
    page.reload.return_value = None
    page.wait_for_load_state.return_value = None
    page.wait_for_selector.return_value = None
    if texts is not None:
        els = [MagicMock(inner_text=MagicMock(return_value=t)) for t in texts]
        page.query_selector_all.return_value = els
    else:
        page.query_selector_all.return_value = []
    page.query_selector.return_value = None
    return page


def _assert_valid_result(result):
    assert isinstance(result, dict)
    assert "data" in result
    assert "screenshots" in result
    assert "network_log" in result
    assert "findings" in result
    assert "auto_approve" in result
    assert isinstance(result["auto_approve"], bool)


# --- multi_page_scrape ---

def test_multi_page_scrape_returns_items_auto_approved():
    from skills.multi_page_scrape import run
    page = _page(["Row 1", "Row 2"])
    result = run(page=page, url="https://example.com", params={"selectors": {"rows": "tr"}, "max_pages": 1}, job_id=1)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "rows" in result["data"]


# --- authenticated_fetch ---

def test_authenticated_fetch_returns_content_auto_approved():
    from skills.authenticated_fetch import run
    page = _page(["Article content here"])
    page.query_selector.return_value = MagicMock()  # found submit button
    result = run(
        page=page,
        url="https://example.com/article",
        params={
            "login_url": "https://example.com/login",
            "username": "user@example.com",
            "password": "secret",
            "username_selector": "#email",
            "password_selector": "#password",
            "submit_selector": "button[type=submit]",
            "content_selector": "article",
        },
        job_id=2,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True


# --- search_scrape ---

def test_search_scrape_returns_results_auto_approved():
    from skills.search_scrape import run
    page = _page(["Result One", "Result Two"])
    result = run(
        page=page,
        url="https://www.google.com/search?q=test",
        params={"result_selector": "h3", "max_results": 10},
        job_id=3,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "results" in result["data"]
```

- [ ] **Step 3: Run tests — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py -v 2>&1 | head -10
```
Expected: `ImportError: No module named 'skills.multi_page_scrape'`

- [ ] **Step 4: Create multi_page_scrape.py**

```python
# archie-scraper/skills/multi_page_scrape.py
"""Skill: multi_page_scrape — Pagination-aware multi-page extraction."""
import logging

logger = logging.getLogger(__name__)

_NEXT_SELECTORS = [
    "a[rel='next']",
    ".pagination-next a",
    "a:has-text('Next')",
    "[aria-label='Next page']",
    "button:has-text('Next')",
]


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        selectors       dict   field_name -> CSS selector
        next_selector   str    CSS for next-page link (optional, auto-detected if omitted)
        max_pages       int    (default 5)
        wait_for        str    CSS to wait for before extracting (optional)
    """
    selectors = params.get("selectors") or {}
    next_sel_override = params.get("next_selector")
    max_pages = int(params.get("max_pages") or 5)
    wait_for = params.get("wait_for")

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    all_data: dict = {field: [] for field in selectors}
    pages_scraped = 0

    for page_num in range(1, max_pages + 1):
        pages_scraped = page_num
        for field, selector in selectors.items():
            els = page.query_selector_all(selector)
            all_data[field].extend(el.inner_text().strip() for el in els)

        next_selectors = [next_sel_override] if next_sel_override else _NEXT_SELECTORS
        next_btn = None
        for sel in next_selectors:
            try:
                next_btn = page.query_selector(sel)
                if next_btn:
                    break
            except Exception:
                continue
        if not next_btn or page_num >= max_pages:
            break
        next_btn.click()
        page.wait_for_load_state("networkidle", timeout=15000)

    total = sum(len(v) for v in all_data.values())
    findings = f"Extracted {total} items across {pages_scraped} page(s) from {url}"
    logger.info("[multi_page_scrape] job #%d: %s", job_id, findings)

    return {
        "data": all_data,
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 5: Create authenticated_fetch.py**

```python
# archie-scraper/skills/authenticated_fetch.py
"""Skill: authenticated_fetch — Login then fetch content behind paywall."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        login_url           str   URL of the login page
        username            str   login username/email
        password            str   login password
        username_selector   str   CSS for username input
        password_selector   str   CSS for password input
        submit_selector     str   CSS for submit button
        content_selector    str   CSS for content to extract after login (optional)
        wait_after_login    str   CSS to wait for after login to confirm success (optional)
    """
    login_url = params.get("login_url") or url
    username = params.get("username", "")
    password = params.get("password", "")
    username_sel = params.get("username_selector", "input[type=email],input[name=username],input[name=email]")
    password_sel = params.get("password_selector", "input[type=password]")
    submit_sel = params.get("submit_selector", "button[type=submit]")
    content_sel = params.get("content_selector")
    wait_after = params.get("wait_after_login")

    # Step 1: navigate to login
    page.goto(login_url, wait_until="networkidle", timeout=30000)

    # Step 2: fill credentials
    try:
        page.fill(username_sel, username)
        page.fill(password_sel, password)
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.press(password_sel, "Enter")
    except Exception as exc:
        findings = f"Login interaction failed: {exc}"
        logger.warning("[authenticated_fetch] job #%d: %s", job_id, findings)
        return {"data": {}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}

    # Step 3: wait for login completion
    if wait_after:
        try:
            page.wait_for_selector(wait_after, timeout=15000)
        except Exception:
            pass
    else:
        page.wait_for_load_state("networkidle", timeout=15000)

    # Step 4: navigate to content URL if different from login URL
    if url and url != login_url:
        page.goto(url, wait_until="networkidle", timeout=30000)

    # Step 5: extract content
    content = ""
    items = []
    if content_sel:
        els = page.query_selector_all(content_sel)
        items = [el.inner_text().strip() for el in els if el.inner_text().strip()]
        content = "\n".join(items[:50])
    else:
        try:
            content = page.inner_text("body")[:2000]
        except Exception:
            content = ""

    findings = f"Fetched {len(items) or 1} item(s) from {url} (authenticated)"
    logger.info("[authenticated_fetch] job #%d: %s", job_id, findings)

    return {
        "data": {"content": content, "items": items, "url": page.url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 6: Create search_scrape.py**

```python
# archie-scraper/skills/search_scrape.py
"""Skill: search_scrape — Navigate search engine/site and extract results."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        result_selector   str   CSS for result items (default: h3,h2)
        link_selector     str   CSS for result links (default: a)
        max_results       int   (default 20)
        wait_for          str   CSS to wait for before extracting (optional)
    """
    result_sel = params.get("result_selector") or "h3,h2"
    link_sel = params.get("link_selector") or "a"
    max_results = int(params.get("max_results") or 20)
    wait_for = params.get("wait_for")

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    result_els = page.query_selector_all(result_sel)[:max_results]
    results = []
    for el in result_els:
        text = el.inner_text().strip()
        if not text:
            continue
        # Try to find closest link ancestor
        href = None
        try:
            link = el.query_selector(link_sel) or el.evaluate_handle(
                "el => el.closest('a')"
            )
            if link:
                href = link.get_attribute("href")
        except Exception:
            pass
        results.append({"text": text[:300], "url": href})

    findings = f"Found {len(results)} results from {url}"
    logger.info("[search_scrape] job #%d: %s", job_id, findings)

    return {
        "data": {"results": results, "source": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 7: Run Task 1 tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_multi_page_scrape_returns_items_auto_approved tests/test_skills_phase2.py::test_authenticated_fetch_returns_content_auto_approved tests/test_skills_phase2.py::test_search_scrape_returns_results_auto_approved -v
```
Expected: 3 passed.

- [ ] **Step 8: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/multi_page_scrape.py \
        archie-scraper/skills/authenticated_fetch.py \
        archie-scraper/skills/search_scrape.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): skills multi_page_scrape, authenticated_fetch, search_scrape"
```

---

## Task 2: Core Scraping — site_change_monitor, pdf_extract, document_download

**Files:**
- Create: `archie-scraper/skills/site_change_monitor.py`
- Create: `archie-scraper/skills/pdf_extract.py`
- Create: `archie-scraper/skills/document_download.py`
- Modify: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Append tests**

Append to `archie-scraper/tests/test_skills_phase2.py`:

```python
# --- site_change_monitor ---

def test_site_change_monitor_detects_change():
    from skills.site_change_monitor import run
    page = MagicMock()
    page.goto.return_value = None
    el = MagicMock()
    el.inner_text.return_value = "New content here"
    page.query_selector.return_value = el
    page.query_selector_all.return_value = [el]
    result = run(
        page=page,
        url="https://example.com",
        params={"content_selector": "main", "stored_hash": "old_hash_abc"},
        job_id=4,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "changed" in result["data"]
    assert "current_hash" in result["data"]


# --- pdf_extract ---

def test_pdf_extract_returns_text_auto_approved():
    from skills.pdf_extract import run
    page = MagicMock()
    page.goto.return_value = None
    link = MagicMock()
    link.get_attribute.return_value = "https://example.com/doc.pdf"
    page.query_selector_all.return_value = [link]
    # Mock the download — no actual HTTP call
    with patch("skills.pdf_extract._download_and_extract", return_value="PDF text content"):
        result = run(
            page=page,
            url="https://example.com",
            params={"pdf_link_selector": "a[href$='.pdf']"},
            job_id=5,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is True


# --- document_download ---

def test_document_download_returns_metadata():
    from skills.document_download import run
    page = MagicMock()
    page.goto.return_value = None
    page.query_selector.return_value = MagicMock()
    with patch("skills.document_download._trigger_download", return_value={"filename": "report.xlsx", "size_bytes": 12345}):
        result = run(
            page=page,
            url="https://example.com",
            params={"download_selector": "a.download-btn"},
            job_id=6,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
```

- [ ] **Step 2: Run — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_site_change_monitor_detects_change -v 2>&1 | head -5
```
Expected: `ImportError`

- [ ] **Step 3: Create site_change_monitor.py**

```python
# archie-scraper/skills/site_change_monitor.py
"""Skill: site_change_monitor — Diff URL content vs stored hash, alert on change."""
import hashlib
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        content_selector   str   CSS to select monitored content (default: body)
        stored_hash        str   Previous MD5 hash to compare against (optional)
    """
    content_sel = params.get("content_selector") or "body"
    stored_hash = params.get("stored_hash") or ""

    page.goto(url, wait_until="networkidle", timeout=30000)

    content = ""
    try:
        els = page.query_selector_all(content_sel)
        content = "\n".join(el.inner_text().strip() for el in els if el.inner_text().strip())
    except Exception:
        content = ""

    current_hash = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()
    changed = bool(stored_hash) and (current_hash != stored_hash)

    findings = (
        f"CHANGED: {url} (hash {stored_hash[:8]}→{current_hash[:8]})"
        if changed
        else f"NO CHANGE: {url} (hash {current_hash[:8]})"
    )
    logger.info("[site_change_monitor] job #%d: %s", job_id, findings)

    return {
        "data": {
            "changed": changed,
            "current_hash": current_hash,
            "stored_hash": stored_hash,
            "content_preview": content[:500],
            "url": url,
        },
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 4: Create pdf_extract.py**

```python
# archie-scraper/skills/pdf_extract.py
"""Skill: pdf_extract — Navigate to page, find PDF links, extract text."""
import io
import logging
import urllib.request

logger = logging.getLogger(__name__)


def _download_and_extract(pdf_url: str) -> str:
    """Download PDF bytes and extract text using basic ASCII filter."""
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        # Basic text extraction: find text between stream markers
        text_parts = []
        i = 0
        while i < len(raw) - 6:
            if raw[i : i + 2] == b"BT":
                end = raw.find(b"ET", i)
                if end > i:
                    chunk = raw[i:end]
                    for part in chunk.split(b"("):
                        close = part.find(b")")
                        if close > 0:
                            try:
                                text_parts.append(part[:close].decode("latin-1"))
                            except Exception:
                                pass
                    i = end + 2
                    continue
            i += 1
        text = " ".join(text_parts)[:5000].strip()
        return text if text else f"[PDF binary, {len(raw)} bytes — no extractable text]"
    except Exception as exc:
        return f"[Download failed: {exc}]"


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        pdf_link_selector   str   CSS to find PDF links (default: a[href$='.pdf'])
        max_pdfs            int   max PDFs to extract (default 3)
    """
    pdf_sel = params.get("pdf_link_selector") or "a[href$='.pdf']"
    max_pdfs = int(params.get("max_pdfs") or 3)

    page.goto(url, wait_until="networkidle", timeout=30000)

    links = page.query_selector_all(pdf_sel)[:max_pdfs]
    pdf_results = []
    for link in links:
        href = link.get_attribute("href") or ""
        if not href:
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(url, href)
        text = _download_and_extract(href)
        pdf_results.append({"url": href, "text": text[:2000]})

    findings = f"Extracted text from {len(pdf_results)} PDF(s) linked from {url}"
    logger.info("[pdf_extract] job #%d: %s", job_id, findings)

    return {
        "data": {"pdfs": pdf_results, "source": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 5: Create document_download.py**

```python
# archie-scraper/skills/document_download.py
"""Skill: document_download — Click download trigger, capture file metadata."""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def _trigger_download(page, selector: str, timeout: int = 30000) -> dict:
    """Click download element, wait for download event, return metadata."""
    result = {"filename": None, "size_bytes": 0}
    with page.expect_download(timeout=timeout) as dl_info:
        btn = page.query_selector(selector)
        if btn:
            btn.click()
        else:
            return result
    download = dl_info.value
    result["filename"] = download.suggested_filename
    tmp = os.path.join(tempfile.gettempdir(), download.suggested_filename or "download")
    download.save_as(tmp)
    try:
        result["size_bytes"] = os.path.getsize(tmp)
        os.unlink(tmp)
    except Exception:
        pass
    return result


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        download_selector   str   CSS for download button/link
        timeout_ms          int   wait for download ms (default 30000)
    """
    download_sel = params.get("download_selector") or "a[download],a[href$='.csv'],a[href$='.xlsx']"
    timeout_ms = int(params.get("timeout_ms") or 30000)

    page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        meta = _trigger_download(page, download_sel, timeout=timeout_ms)
        downloaded = bool(meta.get("filename"))
    except Exception as exc:
        meta = {"filename": None, "size_bytes": 0}
        downloaded = False
        logger.warning("[document_download] job #%d: download failed: %s", job_id, exc)

    findings = (
        f"Downloaded {meta['filename']} ({meta['size_bytes']} bytes) from {url}"
        if downloaded
        else f"No download triggered from {url} using selector '{download_sel}'"
    )
    logger.info("[document_download] job #%d: %s", job_id, findings)

    return {
        "data": {**meta, "downloaded": downloaded, "source": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 6: Run 3 new tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_site_change_monitor_detects_change tests/test_skills_phase2.py::test_pdf_extract_returns_text_auto_approved tests/test_skills_phase2.py::test_document_download_returns_metadata -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/site_change_monitor.py \
        archie-scraper/skills/pdf_extract.py \
        archie-scraper/skills/document_download.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): skills site_change_monitor, pdf_extract, document_download"
```

---

## Task 3: Client UX — login_test, signup_flow, network_inspect

**Files:**
- Create: `archie-scraper/skills/login_test.py`
- Create: `archie-scraper/skills/signup_flow.py`
- Create: `archie-scraper/skills/network_inspect.py`
- Modify: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Append tests**

```python
# --- login_test ---

def test_login_test_captures_flow_needs_review():
    from skills.login_test import run
    page = _page()
    with patch("skills.login_test.save_screenshot", return_value="7/login_form.png"), \
         patch("skills.login_test.screenshot_entry", return_value={"step": "login_form", "path": "7/login_form.png", "caption": "Login form"}):
        result = run(
            page=page,
            url="https://example.com/login",
            params={
                "username": "test@example.com",
                "password": "testpass",
                "username_selector": "#email",
                "password_selector": "#password",
                "submit_selector": "button[type=submit]",
            },
            job_id=7,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert len(result["screenshots"]) >= 1


# --- signup_flow ---

def test_signup_flow_captures_registration_needs_review():
    from skills.signup_flow import run
    page = _page()
    with patch("skills.signup_flow.save_screenshot", return_value="8/signup_form.png"), \
         patch("skills.signup_flow.screenshot_entry", return_value={"step": "signup_form", "path": "8/signup_form.png", "caption": "Signup"}):
        result = run(
            page=page,
            url="https://example.com/signup",
            params={
                "fields": {"#name": "Test User", "#email": "test@example.com"},
                "submit_selector": "button[type=submit]",
            },
            job_id=8,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is False


# --- network_inspect ---

def test_network_inspect_captures_requests_needs_review():
    from skills.network_inspect import run
    page = _page()
    page.on = MagicMock()
    result = run(
        page=page,
        url="https://example.com",
        params={"wait_for_selector": None},
        job_id=9,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "requests_captured" in result["data"]
```

- [ ] **Step 2: Run — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_login_test_captures_flow_needs_review -v 2>&1 | head -5
```

- [ ] **Step 3: Create login_test.py**

```python
# archie-scraper/skills/login_test.py
"""Skill: login_test — Test auth flow, capture all states."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        username            str
        password            str
        username_selector   str
        password_selector   str
        submit_selector     str
        expected_redirect   str   URL fragment expected after successful login (optional)
    """
    username_sel = params.get("username_selector", "input[type=email],input[name=email],input[name=username]")
    password_sel = params.get("password_selector", "input[type=password]")
    submit_sel = params.get("submit_selector", "button[type=submit]")
    expected = params.get("expected_redirect", "")

    screenshots = []
    findings_parts = []

    # Step 1: load login page
    page.goto(url, wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "login_form", page)
    screenshots.append(screenshot_entry("login_form", path, "Login form"))

    # Step 2: fill and submit
    try:
        page.fill(username_sel, params.get("username", ""))
        page.fill(password_sel, params.get("password", ""))
        path = save_screenshot(job_id, "login_filled", page)
        screenshots.append(screenshot_entry("login_filled", path, "Credentials filled"))
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.press(password_sel, "Enter")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        findings_parts.append(f"Submit error: {exc}")

    # Step 3: capture result
    path = save_screenshot(job_id, "post_login", page)
    screenshots.append(screenshot_entry("post_login", path, "Post-login state"))
    final_url = page.url
    success = bool(expected) and expected in final_url

    findings_parts.append(f"Final URL: {final_url}")
    if expected:
        findings_parts.append(f"Expected redirect '{expected}': {'✓' if success else '✗'}")

    return {
        "data": {
            "final_url": final_url,
            "login_success": success,
            "expected_redirect": expected,
        },
        "screenshots": screenshots,
        "network_log": [],
        "findings": "\n".join(findings_parts),
        "auto_approve": False,
    }
```

- [ ] **Step 4: Create signup_flow.py**

```python
# archie-scraper/skills/signup_flow.py
"""Skill: signup_flow — Automate registration and capture result."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        fields          dict   CSS selector -> value (e.g. {"#name": "Test User"})
        submit_selector str
        success_selector str   CSS confirming successful registration (optional)
    """
    fields = params.get("fields") or {}
    submit_sel = params.get("submit_selector", "button[type=submit]")
    success_sel = params.get("success_selector")

    screenshots = []

    page.goto(url, wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "signup_form", page)
    screenshots.append(screenshot_entry("signup_form", path, "Signup form"))

    filled = []
    errors = []
    for selector, value in fields.items():
        try:
            page.fill(selector, str(value))
            filled.append(selector)
        except Exception as exc:
            errors.append(f"{selector}: {exc}")

    try:
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        errors.append(f"Submit: {exc}")

    path = save_screenshot(job_id, "post_signup", page)
    screenshots.append(screenshot_entry("post_signup", path, "Post-signup state"))

    success = False
    if success_sel:
        try:
            page.wait_for_selector(success_sel, timeout=5000)
            success = True
        except Exception:
            pass

    findings = f"Filled {len(filled)}/{len(fields)} fields. " + (
        f"Errors: {'; '.join(errors)}" if errors else "No errors."
    )

    return {
        "data": {"fields_filled": filled, "errors": errors, "success": success, "final_url": page.url},
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 5: Create network_inspect.py**

```python
# archie-scraper/skills/network_inspect.py
"""Skill: network_inspect — Capture all network requests during page load."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        wait_for_selector   str   CSS to wait for before capturing (optional)
        filter_domain       str   only capture requests from this domain (optional)
        include_types       list  request types to capture (default: all)
    """
    wait_for = params.get("wait_for_selector")
    filter_domain = params.get("filter_domain", "")
    include_types = params.get("include_types") or []

    captured: list = []

    def _on_request(req):
        if filter_domain and filter_domain not in req.url:
            return
        if include_types and req.resource_type not in include_types:
            return
        captured.append({
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
            "headers": dict(list(req.headers.items())[:5]),
        })

    def _on_response(resp):
        for item in captured:
            if item["url"] == resp.url and "status" not in item:
                item["status"] = resp.status
                item["content_type"] = resp.headers.get("content-type", "")[:50]

    page.on("request", _on_request)
    page.on("response", _on_response)

    page.goto(url, wait_until="networkidle", timeout=45000)
    if wait_for:
        try:
            page.wait_for_selector(wait_for, timeout=10000)
        except Exception:
            pass

    api_calls = [r for r in captured if r.get("resource_type") in ("xhr", "fetch")]
    findings = f"Captured {len(captured)} requests ({len(api_calls)} API/XHR) from {url}"
    logger.info("[network_inspect] job #%d: %s", job_id, findings)

    return {
        "data": {
            "requests": captured[:200],
            "api_calls": api_calls[:50],
            "requests_captured": len(captured),
            "api_calls_captured": len(api_calls),
        },
        "screenshots": [],
        "network_log": captured[:200],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 6: Run tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_login_test_captures_flow_needs_review tests/test_skills_phase2.py::test_signup_flow_captures_registration_needs_review tests/test_skills_phase2.py::test_network_inspect_captures_requests_needs_review -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/login_test.py \
        archie-scraper/skills/signup_flow.py \
        archie-scraper/skills/network_inspect.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): skills login_test, signup_flow, network_inspect"
```

---

## Task 4: Client UX — accessibility_check, seo_snapshot, broken_link_check

**Files:**
- Create: `archie-scraper/skills/accessibility_check.py`
- Create: `archie-scraper/skills/seo_snapshot.py`
- Create: `archie-scraper/skills/broken_link_check.py`
- Modify: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Append tests**

```python
# --- accessibility_check ---

def test_accessibility_check_returns_report_needs_review():
    from skills.accessibility_check import run
    page = _page()
    page.evaluate.return_value = {"images_missing_alt": 2, "inputs_missing_label": 1, "headings": ["h1", "h2"]}
    result = run(page=page, url="https://example.com", params={}, job_id=10)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "issues" in result["data"] or "checks" in result["data"]


# --- seo_snapshot ---

def test_seo_snapshot_returns_metadata_needs_review():
    from skills.seo_snapshot import run
    page = _page(title="My Site")
    page.evaluate.return_value = {
        "title": "My Site", "meta_description": "A site", "h1": ["Welcome"],
        "canonical": "/", "robots": "index,follow", "og_title": "My Site",
    }
    result = run(page=page, url="https://example.com", params={}, job_id=11)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "title" in result["data"] or "seo" in result["data"]


# --- broken_link_check ---

def test_broken_link_check_returns_link_report():
    from skills.broken_link_check import run
    page = _page()
    link1 = MagicMock()
    link1.get_attribute.return_value = "https://example.com/good"
    link2 = MagicMock()
    link2.get_attribute.return_value = "https://example.com/bad"
    page.query_selector_all.return_value = [link1, link2]
    with patch("skills.broken_link_check._check_url", return_value=200):
        result = run(page=page, url="https://example.com", params={"max_links": 5}, job_id=12)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "links_checked" in result["data"]
```

- [ ] **Step 2: Run — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_accessibility_check_returns_report_needs_review -v 2>&1 | head -5
```

- [ ] **Step 3: Create accessibility_check.py**

```python
# archie-scraper/skills/accessibility_check.py
"""Skill: accessibility_check — Basic WCAG checks via page.evaluate()."""
import logging

logger = logging.getLogger(__name__)

_CHECK_SCRIPT = """() => {
    const results = {};
    // Images without alt
    const imgs = document.querySelectorAll('img');
    results.images_total = imgs.length;
    results.images_missing_alt = Array.from(imgs).filter(i => !i.alt).length;
    // Inputs without label
    const inputs = document.querySelectorAll('input:not([type=hidden]):not([type=submit])');
    results.inputs_total = inputs.length;
    results.inputs_missing_label = Array.from(inputs).filter(i => {
        return !i.labels?.length && !i.getAttribute('aria-label') && !i.getAttribute('aria-labelledby');
    }).length;
    // Heading structure
    results.headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(h => h.tagName.toLowerCase());
    results.has_h1 = results.headings.includes('h1');
    results.h1_count = results.headings.filter(h => h === 'h1').length;
    // Links without text
    const links = document.querySelectorAll('a');
    results.links_no_text = Array.from(links).filter(l => !l.textContent.trim() && !l.getAttribute('aria-label')).length;
    // Lang attribute
    results.html_lang = document.documentElement.lang || null;
    return results;
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        checks = page.evaluate(_CHECK_SCRIPT)
    except Exception as exc:
        checks = {"error": str(exc)}

    issues = []
    if checks.get("images_missing_alt", 0) > 0:
        issues.append(f"{checks['images_missing_alt']} image(s) missing alt text")
    if checks.get("inputs_missing_label", 0) > 0:
        issues.append(f"{checks['inputs_missing_label']} input(s) missing label")
    if not checks.get("has_h1"):
        issues.append("No H1 heading found")
    if checks.get("h1_count", 0) > 1:
        issues.append(f"Multiple H1s ({checks['h1_count']})")
    if not checks.get("html_lang"):
        issues.append("Missing lang attribute on <html>")
    if checks.get("links_no_text", 0) > 0:
        issues.append(f"{checks['links_no_text']} link(s) without accessible text")

    findings = f"{len(issues)} accessibility issue(s) found on {url}: " + (
        "; ".join(issues) if issues else "None"
    )
    logger.info("[accessibility_check] job #%d: %s", job_id, findings)

    return {
        "data": {"checks": checks, "issues": issues, "issue_count": len(issues)},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 4: Create seo_snapshot.py**

```python
# archie-scraper/skills/seo_snapshot.py
"""Skill: seo_snapshot — Extract SEO metadata from a page."""
import logging

logger = logging.getLogger(__name__)

_SEO_SCRIPT = """() => {
    const get = (sel) => { const el = document.querySelector(sel); return el ? el.content || el.href || el.textContent.trim() : null; };
    const getAll = (sel) => Array.from(document.querySelectorAll(sel)).map(e => e.textContent.trim()).filter(Boolean);
    return {
        title: document.title,
        meta_description: get('meta[name="description"]'),
        og_title: get('meta[property="og:title"]'),
        og_description: get('meta[property="og:description"]'),
        og_image: get('meta[property="og:image"]'),
        canonical: get('link[rel="canonical"]'),
        robots: get('meta[name="robots"]'),
        h1: getAll('h1'),
        h2: getAll('h2').slice(0, 10),
        images_count: document.querySelectorAll('img').length,
        images_with_alt: Array.from(document.querySelectorAll('img')).filter(i => i.alt).length,
        links_internal: Array.from(document.querySelectorAll('a[href]')).filter(a => a.hostname === location.hostname).length,
        links_external: Array.from(document.querySelectorAll('a[href]')).filter(a => a.hostname && a.hostname !== location.hostname).length,
        schema_types: Array.from(document.querySelectorAll('[type="application/ld+json"]')).map(s => { try { return JSON.parse(s.textContent)['@type']; } catch(e) { return null; } }).filter(Boolean),
    };
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        seo = page.evaluate(_SEO_SCRIPT)
    except Exception as exc:
        seo = {"error": str(exc)}

    issues = []
    if not seo.get("title"):
        issues.append("Missing title tag")
    elif len(seo.get("title", "")) > 60:
        issues.append(f"Title too long ({len(seo['title'])} chars, max 60)")
    if not seo.get("meta_description"):
        issues.append("Missing meta description")
    if not seo.get("h1") or len(seo.get("h1", [])) == 0:
        issues.append("No H1 tag")
    if not seo.get("canonical"):
        issues.append("No canonical URL")

    findings = f"SEO snapshot for {url}: {len(issues)} issue(s). " + ("; ".join(issues) if issues else "All clear.")
    logger.info("[seo_snapshot] job #%d: %s", job_id, findings)

    return {
        "data": {**seo, "issues": issues},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 5: Create broken_link_check.py**

```python
# archie-scraper/skills/broken_link_check.py
"""Skill: broken_link_check — Spider site and report 404s."""
import logging
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def _check_url(url: str, timeout: int = 10) -> int:
    """Return HTTP status code for url, 0 on connection error."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        max_links       int   max links to check (default 30)
        same_domain     bool  only check same-domain links (default true)
        timeout_ms      int   per-link timeout ms (default 8000)
    """
    max_links = int(params.get("max_links") or 30)
    same_domain = params.get("same_domain", True)
    timeout_sec = int(params.get("timeout_ms") or 8000) // 1000

    page.goto(url, wait_until="networkidle", timeout=30000)

    base_domain = urlparse(url).netloc
    link_els = page.query_selector_all("a[href]")
    hrefs = []
    seen = set()
    for el in link_els:
        href = el.get_attribute("href") or ""
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urljoin(url, href)
        parsed = urlparse(full)
        if same_domain and parsed.netloc != base_domain:
            continue
        if full not in seen:
            seen.add(full)
            hrefs.append(full)
        if len(hrefs) >= max_links:
            break

    broken = []
    for link_url in hrefs:
        status = _check_url(link_url, timeout=timeout_sec)
        if status in (0, 404, 410, 500, 503):
            broken.append({"url": link_url, "status": status, "found_on": url})

    findings = f"Checked {len(hrefs)} links from {url}: {len(broken)} broken"
    logger.info("[broken_link_check] job #%d: %s", job_id, findings)

    return {
        "data": {
            "links_checked": len(hrefs),
            "broken_links": broken,
            "broken_count": len(broken),
        },
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 6: Run 3 new tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_accessibility_check_returns_report_needs_review tests/test_skills_phase2.py::test_seo_snapshot_returns_metadata_needs_review tests/test_skills_phase2.py::test_broken_link_check_returns_link_report -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/accessibility_check.py \
        archie-scraper/skills/seo_snapshot.py \
        archie-scraper/skills/broken_link_check.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): skills accessibility_check, seo_snapshot, broken_link_check"
```

---

## Task 5: Client UX — screenshot_diff, form_audit, competitor_snapshot

**Files:**
- Create: `archie-scraper/skills/screenshot_diff.py`
- Create: `archie-scraper/skills/form_audit.py`
- Create: `archie-scraper/skills/competitor_snapshot.py`
- Modify: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Append tests**

```python
# --- screenshot_diff ---

def test_screenshot_diff_returns_comparison_needs_review():
    from skills.screenshot_diff import run
    page = _page()
    with patch("skills.screenshot_diff.save_screenshot", return_value="13/current.png"), \
         patch("skills.screenshot_diff.screenshot_entry", return_value={"step": "current", "path": "13/current.png", "caption": "Current"}), \
         patch("skills.screenshot_diff._compare_images", return_value=0.95):
        result = run(
            page=page,
            url="https://example.com",
            params={"baseline_path": "/tmp/baseline.png", "threshold": 0.9},
            job_id=13,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "similarity" in result["data"]


# --- form_audit ---

def test_form_audit_returns_form_analysis_needs_review():
    from skills.form_audit import run
    page = _page()
    page.evaluate.return_value = [
        {"action": "/submit", "method": "POST", "field_count": 3, "has_csrf": True, "fields": []}
    ]
    result = run(page=page, url="https://example.com", params={}, job_id=14)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "forms" in result["data"]


# --- competitor_snapshot ---

def test_competitor_snapshot_captures_pages_needs_review():
    from skills.competitor_snapshot import run
    page = _page(title="Competitor Site")
    page.evaluate.return_value = {}
    with patch("skills.competitor_snapshot.save_screenshot", return_value="15/homepage.png"), \
         patch("skills.competitor_snapshot.screenshot_entry", return_value={"step": "homepage", "path": "15/homepage.png", "caption": "Homepage"}):
        result = run(
            page=page,
            url="https://competitor.com",
            params={"pages": ["homepage"]},
            job_id=15,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "screenshots" in result
```

- [ ] **Step 2: Run — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_screenshot_diff_returns_comparison_needs_review -v 2>&1 | head -5
```

- [ ] **Step 3: Create screenshot_diff.py**

```python
# archie-scraper/skills/screenshot_diff.py
"""Skill: screenshot_diff — Compare current screenshot to stored baseline."""
import logging
import os

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def _compare_images(current_path: str, baseline_path: str) -> float:
    """Return 0.0-1.0 similarity score using Pillow pixel diff."""
    try:
        from PIL import Image, ImageChops
        import math

        img1 = Image.open(baseline_path).convert("RGB")
        img2 = Image.open(current_path).convert("RGB")
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)
        diff = ImageChops.difference(img1, img2)
        pixels = list(diff.getdata())
        total = sum(sum(p) for p in pixels)
        max_possible = len(pixels) * 3 * 255
        return 1.0 - (total / max_possible) if max_possible > 0 else 1.0
    except Exception as exc:
        logger.warning("screenshot_diff compare failed: %s", exc)
        return -1.0


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        baseline_path   str   absolute path to baseline PNG
        threshold       float similarity threshold (default 0.9)
    """
    baseline_path = params.get("baseline_path") or ""
    threshold = float(params.get("threshold") or 0.9)

    page.goto(url, wait_until="networkidle", timeout=30000)
    current_path_rel = save_screenshot(job_id, "current", page)

    # Resolve absolute path for comparison
    screenshot_dir = os.getenv("SCREENSHOT_DIR", "/mnt/screenshots")
    current_abs = os.path.join(screenshot_dir, current_path_rel)

    similarity = -1.0
    has_baseline = baseline_path and os.path.exists(baseline_path)
    if has_baseline:
        similarity = _compare_images(current_abs, baseline_path)

    changed = has_baseline and similarity >= 0 and similarity < threshold
    screenshots = [screenshot_entry("current", current_path_rel, f"Current (similarity={similarity:.2%})")]

    findings = (
        f"Visual diff: similarity={similarity:.2%} (threshold {threshold:.0%}) — {'CHANGED' if changed else 'OK'}"
        if has_baseline
        else f"No baseline provided — saved current screenshot to {current_path_rel}"
    )
    logger.info("[screenshot_diff] job #%d: %s", job_id, findings)

    return {
        "data": {
            "similarity": similarity,
            "threshold": threshold,
            "changed": changed,
            "has_baseline": has_baseline,
            "current_path": current_path_rel,
        },
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 4: Create form_audit.py**

```python
# archie-scraper/skills/form_audit.py
"""Skill: form_audit — Analyze all forms on a page."""
import logging

logger = logging.getLogger(__name__)

_FORM_SCRIPT = """() => {
    return Array.from(document.querySelectorAll('form')).map(form => {
        const fields = Array.from(form.querySelectorAll('input,select,textarea')).map(f => ({
            name: f.name || f.id || null,
            type: f.type || f.tagName.toLowerCase(),
            required: f.required,
            label: (() => {
                if (f.id) {
                    const lbl = document.querySelector('label[for="' + f.id + '"]');
                    if (lbl) return lbl.textContent.trim();
                }
                return f.getAttribute('aria-label') || f.placeholder || null;
            })(),
        }));
        const has_csrf = !!(form.querySelector('[name*="csrf"],[name*="token"],[name*="_token"]'));
        return {
            action: form.action || null,
            method: (form.method || 'GET').toUpperCase(),
            field_count: fields.length,
            has_csrf: has_csrf,
            fields: fields,
        };
    });
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        forms = page.evaluate(_FORM_SCRIPT)
    except Exception as exc:
        forms = []
        logger.warning("[form_audit] job #%d: evaluate failed: %s", job_id, exc)

    issues = []
    for i, form in enumerate(forms):
        if form.get("method") == "POST" and not form.get("has_csrf"):
            issues.append(f"Form {i+1} (action={form.get('action')}) missing CSRF token")
        for field in form.get("fields", []):
            if field.get("required") and not field.get("label"):
                issues.append(f"Required field '{field.get('name')}' in form {i+1} has no label")

    findings = f"Found {len(forms)} form(s) on {url}. {len(issues)} issue(s): " + (
        "; ".join(issues) if issues else "None"
    )
    logger.info("[form_audit] job #%d: %s", job_id, findings)

    return {
        "data": {"forms": forms, "form_count": len(forms), "issues": issues},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 5: Create competitor_snapshot.py**

```python
# archie-scraper/skills/competitor_snapshot.py
"""Skill: competitor_snapshot — Full competitive intelligence snapshot."""
import logging
from urllib.parse import urljoin

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)

_TECH_SCRIPT = """() => {
    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
    const tech = [];
    if (scripts.some(s => s.includes('react'))) tech.push('React');
    if (scripts.some(s => s.includes('vue'))) tech.push('Vue');
    if (scripts.some(s => s.includes('angular'))) tech.push('Angular');
    if (scripts.some(s => s.includes('jquery'))) tech.push('jQuery');
    if (scripts.some(s => s.includes('next'))) tech.push('Next.js');
    if (scripts.some(s => s.includes('gatsby'))) tech.push('Gatsby');
    if (document.querySelector('[data-wf-page]')) tech.push('Webflow');
    if (document.querySelector('.wp-content,.wp-block')) tech.push('WordPress');
    const jobs = document.querySelectorAll('a[href*="career"],a[href*="job"],a[href*="hiring"]').length;
    return {tech, jobs_links: jobs, meta_generator: document.querySelector('meta[name=generator]')?.content || null};
}"""

_DEFAULT_PAGES = ["homepage", "pricing", "features"]


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        pages   list   page types to capture (default: homepage, pricing, features)
    """
    pages = params.get("pages") or _DEFAULT_PAGES
    _PAGE_PATHS = {
        "homepage": "",
        "pricing": "/pricing",
        "features": "/features",
        "careers": "/careers",
        "about": "/about",
        "blog": "/blog",
    }

    screenshots = []
    snapshot: dict = {"pages": {}}

    for page_name in pages:
        path = _PAGE_PATHS.get(page_name, f"/{page_name}")
        page_url = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
        try:
            page.goto(page_url, wait_until="networkidle", timeout=30000)
            sc_path = save_screenshot(job_id, page_name, page)
            screenshots.append(screenshot_entry(page_name, sc_path, f"{page_name.title()} page"))
            title = page.title()
            page_data = {"title": title, "url": page.url}
            if page_name == "homepage":
                try:
                    page_data.update(page.evaluate(_TECH_SCRIPT))
                except Exception:
                    pass
            snapshot["pages"][page_name] = page_data
        except Exception as exc:
            snapshot["pages"][page_name] = {"error": str(exc)}

    tech = snapshot.get("pages", {}).get("homepage", {}).get("tech", [])
    findings = f"Captured {len(screenshots)}/{len(pages)} pages from {url}. Tech: {', '.join(tech) or 'unknown'}"
    logger.info("[competitor_snapshot] job #%d: %s", job_id, findings)

    return {
        "data": snapshot,
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
```

- [ ] **Step 6: Run 3 new tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_screenshot_diff_returns_comparison_needs_review tests/test_skills_phase2.py::test_form_audit_returns_form_analysis_needs_review tests/test_skills_phase2.py::test_competitor_snapshot_captures_pages_needs_review -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/screenshot_diff.py \
        archie-scraper/skills/form_audit.py \
        archie-scraper/skills/competitor_snapshot.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): skills screenshot_diff, form_audit, competitor_snapshot"
```

---

## Task 6: Domain-Specific Skills — ancestry_research, crm_enrich, contact_harvest, social_profile_check, price_monitor

**Files:**
- Create: `archie-scraper/skills/ancestry_research.py`
- Create: `archie-scraper/skills/crm_enrich.py`
- Create: `archie-scraper/skills/contact_harvest.py`
- Create: `archie-scraper/skills/social_profile_check.py`
- Create: `archie-scraper/skills/price_monitor.py`
- Modify: `archie-scraper/tests/test_skills_phase2.py`

- [ ] **Step 1: Append tests**

```python
# --- ancestry_research ---

def test_ancestry_research_returns_records_auto_approved():
    from skills.ancestry_research import run
    page = _page(["John Smith b.1852", "Mary Smith b.1855"])
    with patch("skills.ancestry_research.save_screenshot", return_value="16/results.png"), \
         patch("skills.ancestry_research.screenshot_entry", return_value={"step": "results", "path": "16/results.png", "caption": "Results"}):
        result = run(
            page=page,
            url="https://www.ancestry.com/search",
            params={"username": "user@example.com", "password": "pass", "search_name": "John Smith"},
            job_id=16,
        )
    _assert_valid_result(result)
    assert result["auto_approve"] is True


# --- crm_enrich ---

def test_crm_enrich_returns_profile_auto_approved():
    from skills.crm_enrich import run
    page = _page()
    page.evaluate.return_value = {"name": "Jane Doe", "headline": "CEO", "company": "Acme", "location": "Montreal", "followers": "500+"}
    result = run(
        page=page,
        url="https://www.linkedin.com/in/janedoe/",
        params={},
        job_id=17,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "profile" in result["data"]


# --- contact_harvest ---

def test_contact_harvest_extracts_contacts_auto_approved():
    from skills.contact_harvest import run
    page = _page()
    page.evaluate.return_value = {"emails": ["info@example.com"], "phones": ["514-555-1234"], "addresses": []}
    result = run(page=page, url="https://example.com", params={}, job_id=18)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "emails" in result["data"]


# --- social_profile_check ---

def test_social_profile_check_returns_snapshot_auto_approved():
    from skills.social_profile_check import run
    page = _page(title="@testuser on Twitter")
    page.evaluate.return_value = {"followers": "1,234", "following": "567", "posts": "89"}
    result = run(
        page=page,
        url="https://twitter.com/testuser",
        params={"platform": "twitter"},
        job_id=19,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "profile" in result["data"]


# --- price_monitor ---

def test_price_monitor_extracts_prices_auto_approved():
    from skills.price_monitor import run
    price_el = MagicMock()
    price_el.inner_text.return_value = "$99.99"
    title_el = MagicMock()
    title_el.inner_text.return_value = "Widget Pro"
    page = _page()
    page.query_selector_all.side_effect = lambda sel: [price_el] if "price" in sel else [title_el]
    result = run(
        page=page,
        url="https://example.com/product",
        params={"price_selector": ".price", "title_selector": "h1"},
        job_id=20,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "items" in result["data"]
```

- [ ] **Step 2: Run — verify failure**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py::test_ancestry_research_returns_records_auto_approved -v 2>&1 | head -5
```

- [ ] **Step 3: Create ancestry_research.py**

```python
# archie-scraper/skills/ancestry_research.py
"""Skill: ancestry_research — Ancestry.com behind login record search."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        username        str   Ancestry.com login email
        password        str   Ancestry.com login password
        search_name     str   Person name to search
        birth_year      str   Approximate birth year (optional)
        birth_location  str   Birth location (optional)
    """
    username = params.get("username", "")
    password = params.get("password", "")
    search_name = params.get("search_name", "")
    birth_year = params.get("birth_year", "")

    screenshots = []

    # Step 1: Log in
    page.goto("https://www.ancestry.com/account/signin", wait_until="networkidle", timeout=30000)
    try:
        page.fill("#username", username)
        page.fill("#password", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        logger.warning("[ancestry_research] job #%d: login failed: %s", job_id, exc)

    # Step 2: Navigate to search
    search_url = url or "https://search.ancestry.com/search/"
    page.goto(search_url, wait_until="networkidle", timeout=30000)

    # Fill search if on search page
    try:
        page.fill("#sb_firstName", search_name.split()[0] if search_name else "")
        page.fill("#sb_lastName", " ".join(search_name.split()[1:]) if " " in search_name else "")
        if birth_year:
            page.fill("[name*='birthYear'],[name*='BirthYear']", str(birth_year))
        page.click("button[type=submit],[id*=search]")
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    path = save_screenshot(job_id, "results", page)
    screenshots.append(screenshot_entry("results", path, f"Ancestry results for {search_name}"))

    # Extract results
    records = []
    try:
        result_els = page.query_selector_all(".searchResultItem,.card-body,.result-item")
        for el in result_els[:20]:
            text = el.inner_text().strip()
            if text:
                records.append({"text": text[:300]})
    except Exception:
        pass

    findings = f"Found {len(records)} record(s) for '{search_name}' on Ancestry"
    logger.info("[ancestry_research] job #%d: %s", job_id, findings)

    return {
        "data": {"records": records, "search_name": search_name},
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 4: Create crm_enrich.py**

```python
# archie-scraper/skills/crm_enrich.py
"""Skill: crm_enrich — LinkedIn company/person profile scraping."""
import logging

logger = logging.getLogger(__name__)

_PROFILE_SCRIPT = """() => {
    const get = sel => { const el = document.querySelector(sel); return el ? el.textContent.trim() : null; };
    return {
        name: get('.text-heading-xlarge,.pv-text-details__left-panel h1,h1'),
        headline: get('.text-body-medium.break-words,.pv-text-details__left-panel .text-body-medium'),
        location: get('.text-body-small.inline.t-black--light.break-words,[class*="location"]'),
        followers: get('[class*="follower"],[class*="connection"]'),
        about: get('#about + div .full-width,#about ~ div .pv-shared-text-with-see-more'),
        company: get('[data-field="experience_company_logo"]~div h3,.experience-group-position__company-name'),
    };
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params: none required — url is the LinkedIn profile URL
    """
    page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        profile = page.evaluate(_PROFILE_SCRIPT)
    except Exception as exc:
        profile = {"error": str(exc)}

    findings = f"LinkedIn profile scraped: {profile.get('name', 'unknown')} @ {profile.get('company', '?')} from {url}"
    logger.info("[crm_enrich] job #%d: %s", job_id, findings)

    return {
        "data": {"profile": profile, "source_url": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 5: Create contact_harvest.py**

```python
# archie-scraper/skills/contact_harvest.py
"""Skill: contact_harvest — Extract contact information from business site."""
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_CONTACT_SCRIPT = """() => {
    const text = document.body.innerText;
    const emailRe = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;
    const phoneRe = /[\+]?[(]?[0-9]{3}[)]?[\s.\-]?[0-9]{3}[\s.\-]?[0-9]{4}/g;
    const emails = [...new Set(text.match(emailRe) || [])].slice(0, 20);
    const phones = [...new Set(text.match(phoneRe) || [])].slice(0, 10);
    const addresses = [];
    document.querySelectorAll('address,[class*="address"],[itemtype*="PostalAddress"]').forEach(el => {
        const addr = el.textContent.trim();
        if (addr && addr.length > 10) addresses.push(addr.slice(0, 200));
    });
    const team = [];
    document.querySelectorAll('[class*="team"],[class*="member"],[class*="staff"]').forEach(el => {
        const name = el.querySelector('h3,h4,.name')?.textContent?.trim();
        const title = el.querySelector('p,.title,.role')?.textContent?.trim();
        if (name) team.push({name, title});
    });
    return {emails, phones, addresses: [...new Set(addresses)], team: team.slice(0, 20)};
}"""

_CONTACT_PAGES = ["/contact", "/about", "/team", "/contact-us", "/about-us"]


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        extra_pages   list  additional relative paths to scrape (optional)
    """
    extra = params.get("extra_pages") or []
    all_data: dict = {"emails": [], "phones": [], "addresses": [], "team": []}
    seen_emails: set = set()

    pages_to_check = [url] + [urljoin(url, p) for p in _CONTACT_PAGES + extra]

    for page_url in pages_to_check[:6]:
        try:
            page.goto(page_url, wait_until="networkidle", timeout=20000)
            result = page.evaluate(_CONTACT_SCRIPT)
            for email in result.get("emails", []):
                if email not in seen_emails:
                    seen_emails.add(email)
                    all_data["emails"].append(email)
            for phone in result.get("phones", []):
                if phone not in all_data["phones"]:
                    all_data["phones"].append(phone)
            all_data["addresses"].extend(result.get("addresses", []))
            all_data["team"].extend(result.get("team", []))
        except Exception:
            continue

    # Deduplicate
    all_data["addresses"] = list(dict.fromkeys(all_data["addresses"]))[:10]
    all_data["team"] = all_data["team"][:30]

    findings = (
        f"Harvested {len(all_data['emails'])} emails, "
        f"{len(all_data['phones'])} phones, "
        f"{len(all_data['team'])} team members from {url}"
    )
    logger.info("[contact_harvest] job #%d: %s", job_id, findings)

    return {
        "data": all_data,
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 6: Create social_profile_check.py**

```python
# archie-scraper/skills/social_profile_check.py
"""Skill: social_profile_check — Snapshot public social media profiles."""
import logging

logger = logging.getLogger(__name__)

_PLATFORM_SCRIPTS = {
    "twitter": """() => ({
        name: document.querySelector('[data-testid="UserName"] span')?.textContent?.trim(),
        bio: document.querySelector('[data-testid="UserDescription"]')?.textContent?.trim(),
        followers: document.querySelector('[href$="/followers"] span')?.textContent?.trim(),
        following: document.querySelector('[href$="/following"] span')?.textContent?.trim(),
    })""",
    "linkedin": """() => ({
        name: document.querySelector('h1')?.textContent?.trim(),
        headline: document.querySelector('.text-body-medium')?.textContent?.trim(),
        followers: document.querySelector('[class*="follower"]')?.textContent?.trim(),
    })""",
    "instagram": """() => ({
        name: document.querySelector('header h2')?.textContent?.trim(),
        bio: document.querySelector('header section > div:last-child span')?.textContent?.trim(),
        posts: document.querySelectorAll('article img').length,
    })""",
    "default": """() => ({
        title: document.title,
        meta_description: document.querySelector('meta[name="description"]')?.content,
    })""",
}


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        platform   str   linkedin | twitter | instagram (auto-detected from URL if omitted)
    """
    platform = params.get("platform") or ""
    if not platform:
        if "linkedin" in url:
            platform = "linkedin"
        elif "twitter" in url or "x.com" in url:
            platform = "twitter"
        elif "instagram" in url:
            platform = "instagram"
        else:
            platform = "default"

    script = _PLATFORM_SCRIPTS.get(platform, _PLATFORM_SCRIPTS["default"])

    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        profile = page.evaluate(script)
    except Exception as exc:
        profile = {"error": str(exc)}

    findings = f"{platform.title()} profile scraped from {url}: {profile.get('name') or profile.get('title', 'unknown')}"
    logger.info("[social_profile_check] job #%d: %s", job_id, findings)

    return {
        "data": {"profile": profile, "platform": platform, "source_url": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 7: Create price_monitor.py**

```python
# archie-scraper/skills/price_monitor.py
"""Skill: price_monitor — Track product/competitor prices over time."""
import logging
import re

logger = logging.getLogger(__name__)

_CURRENCY_RE = re.compile(r"[\$£€¥₹CAD\s]*[\d,]+\.?\d*")


def _parse_price(text: str) -> str:
    """Extract first price-like value from text."""
    text = text.strip()
    match = _CURRENCY_RE.search(text)
    return match.group(0).strip() if match else text


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        price_selector   str   CSS for price element(s)
        title_selector   str   CSS for product title (optional)
        stock_selector   str   CSS for in-stock indicator (optional)
        max_items        int   max items to extract (default 10)
    """
    price_sel = params.get("price_selector") or ".price,#price,[class*='price']"
    title_sel = params.get("title_selector") or "h1,[class*='product-title'],[class*='item-name']"
    stock_sel = params.get("stock_selector") or "[class*='stock'],[class*='availability']"
    max_items = int(params.get("max_items") or 10)

    page.goto(url, wait_until="networkidle", timeout=30000)

    price_els = page.query_selector_all(price_sel)[:max_items]
    title_els = page.query_selector_all(title_sel)[:max_items]
    stock_els = page.query_selector_all(stock_sel)[:max_items]

    items = []
    for i in range(max(len(price_els), 1)):
        price_text = price_els[i].inner_text().strip() if i < len(price_els) else ""
        title_text = title_els[i].inner_text().strip() if i < len(title_els) else ""
        stock_text = stock_els[i].inner_text().strip() if i < len(stock_els) else ""
        items.append({
            "title": title_text[:200],
            "price_raw": price_text,
            "price": _parse_price(price_text),
            "in_stock": "out" not in stock_text.lower() if stock_text else None,
            "source": url,
        })

    findings = f"Monitored {len(items)} item(s) from {url}: " + (
        ", ".join(f"{i['title'][:30] or 'item'} @ {i['price']}" for i in items[:3])
    )
    logger.info("[price_monitor] job #%d: %s", job_id, findings)

    return {
        "data": {"items": items, "source": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 8: Run 5 domain-specific tests**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest \
  tests/test_skills_phase2.py::test_ancestry_research_returns_records_auto_approved \
  tests/test_skills_phase2.py::test_crm_enrich_returns_profile_auto_approved \
  tests/test_skills_phase2.py::test_contact_harvest_extracts_contacts_auto_approved \
  tests/test_skills_phase2.py::test_social_profile_check_returns_snapshot_auto_approved \
  tests/test_skills_phase2.py::test_price_monitor_extracts_prices_auto_approved -v
```
Expected: 5 passed.

- [ ] **Step 9: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/skills/ancestry_research.py \
        archie-scraper/skills/crm_enrich.py \
        archie-scraper/skills/contact_harvest.py \
        archive-scraper/skills/social_profile_check.py \
        archie-scraper/skills/price_monitor.py \
        archie-scraper/tests/test_skills_phase2.py
git commit -m "feat(scout): domain-specific skills ancestry, crm_enrich, contact_harvest, social_profile_check, price_monitor"
```

---

## Task 7: Register all 20 skills in SKILL_MAP + full test suite

**Files:**
- Modify: `archie-scraper/job_worker.py`

- [ ] **Step 1: Update SKILL_MAP in job_worker.py**

Find the `SKILL_MAP` dict at the top of job_worker.py (currently has 3 entries: web_scrape, ux_audit, procurement_sync) and replace it with:

```python
SKILL_MAP = {
    # Core data collection
    "web_scrape": "skills.web_scrape",
    "multi_page_scrape": "skills.multi_page_scrape",
    "authenticated_fetch": "skills.authenticated_fetch",
    "search_scrape": "skills.search_scrape",
    "site_change_monitor": "skills.site_change_monitor",
    "pdf_extract": "skills.pdf_extract",
    "document_download": "skills.document_download",
    # Client UX intelligence
    "ux_audit": "skills.ux_audit",
    "login_test": "skills.login_test",
    "signup_flow": "skills.signup_flow",
    "network_inspect": "skills.network_inspect",
    "accessibility_check": "skills.accessibility_check",
    "seo_snapshot": "skills.seo_snapshot",
    "broken_link_check": "skills.broken_link_check",
    "screenshot_diff": "skills.screenshot_diff",
    "form_audit": "skills.form_audit",
    "competitor_snapshot": "skills.competitor_snapshot",
    # Domain-specific
    "procurement_sync": "skills.procurement_sync",
    "ancestry_research": "skills.ancestry_research",
    "crm_enrich": "skills.crm_enrich",
    "contact_harvest": "skills.contact_harvest",
    "social_profile_check": "skills.social_profile_check",
    "price_monitor": "skills.price_monitor",
}
```

Also update `enqueue()` — the `auto_approve` check should include all data-collection skills:

```python
    auto_approve = job_type in {
        "web_scrape", "multi_page_scrape", "authenticated_fetch",
        "search_scrape", "site_change_monitor", "pdf_extract",
        "document_download", "procurement_sync", "ancestry_research",
        "crm_enrich", "contact_harvest", "social_profile_check", "price_monitor",
    }
```

- [ ] **Step 2: Run full Phase 2 test suite**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/test_skills_phase2.py -v 2>&1 | tail -25
```
Expected: 20 passed.

- [ ] **Step 3: Run complete test suite (Phase 1 + Phase 2)**
```bash
cd /mnt/archie_brain/archie-scraper && python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: 33 passed (13 Phase 1 + 20 Phase 2).

- [ ] **Step 4: Verify archie_scraper still healthy after restart**
```bash
cd /mnt/archie_brain && docker compose build archie_scraper 2>&1 | tail -3
docker compose up -d archie_scraper
sleep 8
docker exec archie_platform python3 -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://archie_scraper:4243/health', timeout=5).read()))"
```
Expected: `{'status': 'ok', 'pool_size': 3, 'slots_available': 3}`

- [ ] **Step 5: Submit a smoke test with a new Phase 2 skill**
```bash
docker exec archie_platform python3 -c "
import urllib.request, json, time
payload = json.dumps({
    'job_type': 'seo_snapshot',
    'target_url': 'https://canadabuys.canada.ca',
    'params': {},
    'requested_by': 'phase2_smoke',
}).encode()
req = urllib.request.Request('http://archie_scraper:4243/jobs', data=payload)
req.add_header('Content-Type', 'application/json')
r = urllib.request.urlopen(req, timeout=10)
job = json.loads(r.read())
print('Submitted:', job)
for _ in range(12):
    time.sleep(5)
    r2 = urllib.request.urlopen(f'http://archie_scraper:4243/jobs/{job[\"job_id\"]}', timeout=5)
    d = json.loads(r2.read())
    print('Status:', d['status'])
    if d['status'] not in ('pending', 'running'):
        print('Findings:', d.get('findings', '')[:200])
        break
"
```
Expected: `needs_review` status (seo_snapshot has auto_approve=False).

- [ ] **Step 6: Commit**
```bash
cd /mnt/archie_brain
git add archie-scraper/job_worker.py
git commit -m "feat(scout): register all 23 skills in SKILL_MAP + auto_approve set"
```

- [ ] **Step 7: Create PR**
```bash
cd /mnt/archie_brain
git push -u origin feat/scout-phase2
gh pr create \
  --title "feat(scout): Phase 2 — full 23-skill browser intelligence suite" \
  --body "$(cat <<'EOF'
## Summary
- 20 new skills added to archie-scraper/skills/: multi_page_scrape, authenticated_fetch, search_scrape, site_change_monitor, pdf_extract, document_download, login_test, signup_flow, network_inspect, accessibility_check, seo_snapshot, broken_link_check, screenshot_diff, form_audit, competitor_snapshot, ancestry_research, crm_enrich, contact_harvest, social_profile_check, price_monitor
- SKILL_MAP in job_worker.py updated to all 23 skills
- auto_approve whitelist updated for all data-collection skills
- 33/33 total tests pass (13 Phase 1 + 20 Phase 2)

## Coverage by module
- Gov-watch: procurement_sync, pdf_extract, multi_page_scrape, site_change_monitor
- WTF: authenticated_fetch (Toronto Star, La Presse)
- Family Tree: ancestry_research
- KBS CRM: crm_enrich, contact_harvest
- KBS kbs_scout: ux_audit, login_test, signup_flow, network_inspect, accessibility_check, seo_snapshot, broken_link_check, screenshot_diff, form_audit, competitor_snapshot
- Market Watch: price_monitor
- S.I.G.N.A.L.: social_profile_check

## Test Plan
- [x] 33/33 unit tests pass
- [x] archie_scraper health OK after rebuild
- [x] seo_snapshot smoke job reaches needs_review

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage — all 20 Phase 2 skills:**

| Skill | Task | auto_approve |
|---|---|---|
| multi_page_scrape | 1 | True |
| authenticated_fetch | 1 | True |
| search_scrape | 1 | True |
| site_change_monitor | 2 | True |
| pdf_extract | 2 | True |
| document_download | 2 | True |
| login_test | 3 | False |
| signup_flow | 3 | False |
| network_inspect | 3 | False |
| accessibility_check | 4 | False |
| seo_snapshot | 4 | False |
| broken_link_check | 4 | False |
| screenshot_diff | 5 | False |
| form_audit | 5 | False |
| competitor_snapshot | 5 | False |
| ancestry_research | 6 | True |
| crm_enrich | 6 | True |
| contact_harvest | 6 | True |
| social_profile_check | 6 | True |
| price_monitor | 6 | True |

**SKILL_MAP registration:** Task 7 ✅
**auto_approve whitelist update:** Task 7 ✅
**Smoke test after rebuild:** Task 7 ✅
