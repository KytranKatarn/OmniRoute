"""mailbox_scout_capture.py — S.C.O.U.T. autonomous capture of a public AI chat SHARE link
into the Mailbox Story Extractor.

Renders the share URL server-side via the archie_scraper (S.C.O.U.T.) fabric using the
`chat_capture` skill, then lands the transcript through mailbox_chat_service.ingest_chat — the
SAME pipeline as emails/exports, so the existing enrichment + story workers process it via DHQ
(capability='analyze', local_only=True — welfare-gated). No new dispatch path.

A share link is a frozen SNAPSHOT (only what was visible when shared). For COMPLETE history use
the data-export path (mailbox_chat_service.ingest_export_file). This is the convenience /
autonomous path for a single shared thread, exposed as a delegate_task known-tool shortcut so
A.R.C.H.I.E. agents can capture it without an LLM round-trip.
"""

import logging
import time

import requests

from services.mailbox_chat_service import ingest_chat

logger = logging.getLogger(__name__)

_SCRAPER_BASE = "http://archie_scraper:4243"
# scout_jobs terminal states that carry a `data` payload (auto_approve -> approved;
# otherwise needs_review). 'completed' kept for forward-compat.
_TERMINAL_OK = {"approved", "needs_review", "completed"}


def capture_share(url, owner_id=None, title=None, timeout_s=120):
    """Render a chat share URL via S.C.O.U.T. and ingest the transcript into Mailbox Story.

    Returns {"import_id", "messages", "title", "selector"} on success, or {"error": ...}.
    Synchronous (polls the async scraper job) — web-request callers should run it in a thread.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"error": "provide a valid http(s) share URL"}

    try:
        sub = requests.post(
            f"{_SCRAPER_BASE}/jobs",
            json={
                "job_type": "chat_capture",
                "target_url": url,
                "params": {},
                "requested_by": "mailbox_story",
            },
            timeout=15,
        )
        sub.raise_for_status()
        job_id = (sub.json() or {}).get("job_id")
    except Exception as exc:
        logger.error("chat_capture submit failed for %s: %s", url, exc)
        return {"error": f"scraper submit failed: {exc}"}
    if not job_id:
        return {"error": "scraper returned no job_id"}

    deadline = time.time() + timeout_s
    row = {}
    while time.time() < deadline:
        time.sleep(4)
        try:
            r = requests.get(f"{_SCRAPER_BASE}/jobs/{job_id}", timeout=10)
            r.raise_for_status()
            row = r.json() or {}
        except Exception as exc:
            logger.warning("chat_capture poll job %s failed: %s", job_id, exc)
            continue
        status = row.get("status")
        if status == "failed":
            return {"error": "capture failed", "detail": (row.get("error_log") or "")[:500], "job_id": job_id}
        if status in _TERMINAL_OK:
            break
    else:
        return {"error": f"capture timed out after {timeout_s}s", "job_id": job_id}

    data = row.get("data") or {}
    raw = data.get("messages") or []
    msgs = [(m[0], m[1], None) for m in raw if isinstance(m, (list, tuple)) and len(m) >= 2 and (m[1] or "").strip()]
    if not msgs:
        return {"error": "no messages extracted from the share page", "job_id": job_id}

    import_id = ingest_chat(title or data.get("title") or "shared conversation", msgs, owner_id=owner_id)
    logger.info("chat_capture: import %s from %s (%d messages)", import_id, url, len(msgs))
    return {
        "import_id": import_id,
        "messages": len(msgs),
        "title": title or data.get("title"),
        "selector": data.get("selector"),
        "job_id": job_id,
    }
