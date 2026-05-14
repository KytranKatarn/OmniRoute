"""Skill: document_download — Click download trigger, capture file metadata."""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def _trigger_download(page, selector: str, timeout: int = 30000) -> dict:
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
    download_sel = params.get("download_selector") or "a[download],a[href$='.csv'],a[href$='.xlsx']"
    timeout_ms = int(params.get("timeout_ms") or 30000)

    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        meta = _trigger_download(page, download_sel, timeout=timeout_ms)
        downloaded = bool(meta.get("filename"))
    except Exception as exc:
        meta = {"filename": None, "size_bytes": 0}
        downloaded = False
        logger.warning("[document_download] job #%d: %s", job_id, exc)

    findings = (f"Downloaded {meta['filename']} ({meta['size_bytes']} bytes) from {url}" if downloaded
                else f"No download triggered from {url}")
    return {"data": {**meta, "downloaded": downloaded, "source": url}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}
