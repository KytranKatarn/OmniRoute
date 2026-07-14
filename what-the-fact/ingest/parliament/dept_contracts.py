"""dept_contracts.py — mirror Gov Watch's department contract-award rollup.

The WTF side of the #373 "Contract" chain link. Gov Watch owns the federal
procurement data (CanadaBuys award notices) and exposes a canonical-department
rollup at GET /api/internal/dept-contract-rollup. This daily sync pulls that
tiny aggregate over the mesh and upserts it into parliament.dept_contracts, so
the cost model (cost.py) can sit a minister's office cost beside the federal
contract volume their portfolio oversees — with no cross-product DB coupling
and no runtime dependency on Gov Watch being up (the cache serves between
refreshes).

Fail-loud like every other parliament sync: every run writes
parliament.ingest_log (task='dept_contracts') with the upsert count OR the error,
so the drift guard watches it and it can never silently stop.

Env:
    GOV_WATCH_URL     http://100.64.0.10:8102   Gov Watch on the mesh (NEVER public — the
                                                 Hostinger CDN caps at 60s and hides the call)
    INTERNAL_API_KEY  —                          X-Internal-Key for the rollup endpoint
    WTF_DEPT_CONTRACTS_TIMEOUT  60               HTTP timeout (seconds)
"""
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.parliament")

# Mesh IP, never the public hostname (the CDN caps at 60s + bypasses the queue).
_GOV_URL = os.environ.get("GOV_WATCH_URL", "http://100.64.0.10:8102").rstrip("/")
_INTERNAL_KEY = os.environ.get("INTERNAL_API_KEY", "")
_TIMEOUT = int(os.environ.get("WTF_DEPT_CONTRACTS_TIMEOUT", "60"))


def _fetch_rollup() -> dict:
    """GET the canonical-department rollup from Gov Watch. Raises on any failure."""
    if not _INTERNAL_KEY:
        raise RuntimeError("INTERNAL_API_KEY not set — cannot authenticate to Gov Watch")
    # SSRF guard: this is our own fixed config, but validate scheme+host anyway so a
    # mis-set env can never point the internal key at an arbitrary or public host.
    parts = urlsplit(_GOV_URL)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RuntimeError("GOV_WATCH_URL must be an http(s) URL with a host: %r" % _GOV_URL)
    req = urllib.request.Request(
        _GOV_URL + "/api/internal/dept-contract-rollup",
        headers={"X-Internal-Key": _INTERNAL_KEY},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        if r.status != 200:
            raise RuntimeError("Gov Watch rollup HTTP %s" % r.status)
        payload = json.loads(r.read().decode("utf-8"))
    depts = payload.get("departments")
    if not isinstance(depts, dict) or not depts:
        raise RuntimeError("Gov Watch rollup returned no departments")
    return payload


def _upsert(engine, payload: dict) -> int:
    """Upsert every department row into parliament.dept_contracts. Returns the count."""
    window = payload.get("window") or {}
    source = payload.get("source")
    ws, we = window.get("start"), window.get("end")
    n = 0
    with engine.begin() as conn:
        for dept, d in (payload.get("departments") or {}).items():
            conn.execute(
                text(
                    "INSERT INTO parliament.dept_contracts "
                    "(canonical_dept, total, n, by_fy, central_purchaser, "
                    " window_start, window_end, source, refreshed_at) "
                    "VALUES (:d, :t, :n, CAST(:by_fy AS jsonb), :cp, :ws, :we, :src, now()) "
                    "ON CONFLICT (canonical_dept) DO UPDATE SET "
                    "  total = EXCLUDED.total, n = EXCLUDED.n, by_fy = EXCLUDED.by_fy, "
                    "  central_purchaser = EXCLUDED.central_purchaser, "
                    "  window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end, "
                    "  source = EXCLUDED.source, refreshed_at = now()"
                ),
                {
                    "d": dept,
                    "t": int(d.get("total") or 0),
                    "n": int(d.get("n") or 0),
                    "by_fy": json.dumps(d.get("by_fy") or {}),
                    "cp": bool(d.get("central_purchaser")),
                    "ws": ws,
                    "we": we,
                    "src": source,
                },
            )
            n += 1
    return n


def run_dept_contracts_sync(engine) -> dict:
    """Pull Gov Watch's dept-contract rollup and upsert into parliament.dept_contracts.

    Fail-loud: writes parliament.ingest_log (task='dept_contracts') either way. Returns
    {ok, upserted} or {ok: False, error}. Never raises — a sync that crashes the ingest
    loop is worse than one that logs the error and retries tomorrow.
    """
    try:
        payload = _fetch_rollup()
        upserted = _upsert(engine, payload)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES ('dept_contracts', :f, :u)"
                ),
                {"f": upserted, "u": upserted},
            )
        logger.info("dept_contracts sync: upserted %d departments", upserted)
        return {"ok": True, "upserted": upserted}
    except Exception as exc:
        logger.error("dept_contracts sync failed: %s", exc)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO parliament.ingest_log (task, error) "
                        "VALUES ('dept_contracts', :e)"
                    ),
                    {"e": str(exc)[:500]},
                )
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}
