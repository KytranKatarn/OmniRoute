"""Multi-egress geographic fetch — same URL from N exit IPs for bias detection."""
import hashlib
import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_HUB_URL = os.getenv("BRIDGE_URL", "http://192.168.1.200:3000")
_SCOUT_KEY = os.getenv("CLUSTER_PROXY_KEY", "")
_EGRESS_TIERS = [1, 2]  # Hub residential + VPS outpost


def _submit_fetch(url: str, egress_tier: int) -> "int | None":
    if not _SCOUT_KEY:
        return None
    try:
        payload = json.dumps({
            "job_type": "web_scrape",
            "target_url": url,
            "params": {"selectors": {"body": "article,main,body"}, "max_items": 1},
            "egress_tier": egress_tier,
            "requested_by": "wtf_bias",
        }).encode()
        req = urllib.request.Request(
            f"{_HUB_URL}/tools/department-hq/api/scout/cli-dispatch",
            data=payload,
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Scout-Key", _SCOUT_KEY)
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read()).get("job_id")
    except Exception as exc:
        logger.warning("multi_egress: submit failed tier=%d: %s", egress_tier, exc)
        return None


def _poll_job(job_id: int, max_attempts: int = 12) -> "dict | None":
    import time

    url = f"{_HUB_URL}/tools/department-hq/api/scout/cli-status/{job_id}"
    for _ in range(max_attempts):
        time.sleep(5)
        try:
            req = urllib.request.Request(url)
            req.add_header("X-Scout-Key", _SCOUT_KEY)
            r = urllib.request.urlopen(req, timeout=8)
            result = json.loads(r.read())
            if result.get("status") in ("approved", "completed", "failed"):
                return result
        except Exception:
            pass
    return None


def _content_hash(result: dict) -> str:
    data = result.get("data") or {}
    body = data.get("body") or []
    text = " ".join(body) if isinstance(body, list) else str(body)
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def detect_geographic_variation(url: str) -> dict:
    """Fetch same URL from multiple egress tiers, return variation analysis."""
    if not _SCOUT_KEY:
        return {
            "url": url,
            "results": [],
            "variation_detected": False,
            "hashes": [],
            "error": "CLUSTER_PROXY_KEY not set",
        }

    job_ids = {}
    for tier in _EGRESS_TIERS:
        job_id = _submit_fetch(url, tier)
        if job_id:
            job_ids[tier] = job_id

    results = []
    hashes = []
    for tier, job_id in job_ids.items():
        result = _poll_job(job_id)
        if result and result.get("status") in ("approved", "completed"):
            h = _content_hash(result)
            results.append({"tier": tier, "job_id": job_id, "content_hash": h, "status": "ok"})
            hashes.append(h)
        else:
            results.append({"tier": tier, "job_id": job_id, "content_hash": None, "status": "failed"})

    variation = len({h for h in hashes if h}) > 1
    if variation:
        logger.info("GEOGRAPHIC VARIATION detected: %s — hashes=%s", url[:60], hashes)

    return {
        "url": url,
        "results": results,
        "variation_detected": variation,
        "hashes": hashes,
    }
