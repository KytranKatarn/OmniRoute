"""Skill: pdf_extract — Find PDF links on page and extract text."""
import logging
import urllib.request

logger = logging.getLogger(__name__)


def _download_and_extract(pdf_url: str) -> str:
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        text_parts = []
        i = 0
        while i < len(raw) - 6:
            if raw[i:i+2] == b"BT":
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
        return text if text else f"[PDF binary, {len(raw)} bytes]"
    except Exception as exc:
        return f"[Download failed: {exc}]"


def run(page, url: str, params: dict, job_id: int) -> dict:
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
    return {"data": {"pdfs": pdf_results, "source": url}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}
