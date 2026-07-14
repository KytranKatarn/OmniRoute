"""securities_issuer_contracts.py — mirror Gov Watch's issuer contract-award rollup.

The WTF side of the #373 "Contract -> Market" chain link (Market Slice M2). Gov Watch
owns the federal procurement data (CanadaBuys award notices) and exposes a per-TSX-issuer
rollup at GET /api/internal/issuer-contract-rollup. This daily sync pulls that tiny
aggregate over the mesh and upserts it into securities.issuer_contracts, so the entity
graph's already-live market_reaction_to link (structural: "this company is a federal
contractor") can be surfaced WITH the dollar footprint it lacks — "CAE (TSX:CAE) won $X
in federal contracts."

Fail-loud like every other ingest: every run writes parliament.ingest_log
(task='issuer_contracts') with the upsert count OR the error, so the drift guard watches
it and it can never silently stop. No cross-product DB coupling; the cache serves between
refreshes.

Env:
    GOV_WATCH_URL     http://100.64.0.10:8102   Gov Watch on the mesh (NEVER public — the
                                                 Hostinger CDN caps at 60s and hides the call)
    INTERNAL_API_KEY  —                          X-Internal-Key for the rollup endpoint
    WTF_ISSUER_CONTRACTS_TIMEOUT  60             HTTP timeout (seconds)
"""
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.securities")

# Mesh IP, never the public hostname (the CDN caps at 60s + bypasses the queue).
_GOV_URL = os.environ.get("GOV_WATCH_URL", "http://100.64.0.10:8102").rstrip("/")
_INTERNAL_KEY = os.environ.get("INTERNAL_API_KEY", "")
_TIMEOUT = int(os.environ.get("WTF_ISSUER_CONTRACTS_TIMEOUT", "60"))


def _fetch_rollup() -> dict:
    """GET the per-issuer rollup from Gov Watch. Raises on any failure."""
    if not _INTERNAL_KEY:
        raise RuntimeError("INTERNAL_API_KEY not set — cannot authenticate to Gov Watch")
    # SSRF guard: our own fixed config, but validate scheme+host so a mis-set env can never
    # point the internal key at an arbitrary or public host.
    parts = urlsplit(_GOV_URL)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RuntimeError("GOV_WATCH_URL must be an http(s) URL with a host: %r" % _GOV_URL)
    req = urllib.request.Request(
        _GOV_URL + "/api/internal/issuer-contract-rollup",
        headers={"X-Internal-Key": _INTERNAL_KEY},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        if r.status != 200:
            raise RuntimeError("Gov Watch issuer rollup HTTP %s" % r.status)
        payload = json.loads(r.read().decode("utf-8"))
    issuers = payload.get("issuers")
    if not isinstance(issuers, dict) or not issuers:
        raise RuntimeError("Gov Watch issuer rollup returned no issuers")
    return payload


def _upsert(engine, payload: dict) -> int:
    """Upsert every issuer row into securities.issuer_contracts. Returns the count."""
    window = payload.get("window") or {}
    source = payload.get("source")
    ws, we = window.get("start"), window.get("end")
    n = 0
    with engine.begin() as conn:
        for tk, d in (payload.get("issuers") or {}).items():
            conn.execute(
                text(
                    "INSERT INTO securities.issuer_contracts "
                    "(ticker, name, exchange, jv, total, n, by_fy, "
                    " window_start, window_end, source, refreshed_at) "
                    "VALUES (:tk, :name, :exch, :jv, :t, :n, CAST(:by_fy AS jsonb), "
                    "        :ws, :we, :src, now()) "
                    "ON CONFLICT (ticker) DO UPDATE SET "
                    "  name = EXCLUDED.name, exchange = EXCLUDED.exchange, jv = EXCLUDED.jv, "
                    "  total = EXCLUDED.total, n = EXCLUDED.n, by_fy = EXCLUDED.by_fy, "
                    "  window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end, "
                    "  source = EXCLUDED.source, refreshed_at = now()"
                ),
                {
                    "tk": tk,
                    "name": d.get("name"),
                    "exch": d.get("exchange"),
                    "jv": bool(d.get("jv")),
                    "t": int(d.get("total") or 0),
                    "n": int(d.get("n") or 0),
                    "by_fy": json.dumps(d.get("by_fy") or {}),
                    "ws": ws,
                    "we": we,
                    "src": source,
                },
            )
            n += 1
    return n


def run_issuer_contracts_sync(engine) -> dict:
    """Pull Gov Watch's issuer-contract rollup and upsert into securities.issuer_contracts.

    Fail-loud: writes parliament.ingest_log (task='issuer_contracts') either way. Returns
    {ok, upserted} or {ok: False, error}. Never raises — a sync that crashes the ingest loop
    is worse than one that logs the error and retries tomorrow.
    """
    try:
        payload = _fetch_rollup()
        upserted = _upsert(engine, payload)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES ('issuer_contracts', :f, :u)"
                ),
                {"f": upserted, "u": upserted},
            )
        logger.info("issuer_contracts sync: upserted %d issuers", upserted)
        return {"ok": True, "upserted": upserted}
    except Exception as exc:
        logger.error("issuer_contracts sync failed: %s", exc)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO parliament.ingest_log (task, error) "
                        "VALUES ('issuer_contracts', :e)"
                    ),
                    {"e": str(exc)[:500]},
                )
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}
