"""ingest/securities_issuer_ingest.py — TSX listed-issuer directory (#373 Market L6, Phase 0).

The shared entity graph is NAME-keyed; Market Watch is TICKER-keyed. To light up chain
Link 6 (market_reaction_to, Contract -> Market) we first need a name<->ticker bridge: an
issuer directory of Canadian public companies. This module builds it.

Source: the S&P/TSX 60 + S&P/TSX Composite constituents from Wikipedia (public, no key,
the large/mid-cap universe — exactly the issuers large enough to win federal contracts;
the gov-procurement overlap is the binding constraint, not raw issuer count). Parsed from
the rendered HTML tables with regex (no bs4 dependency). Can be widened to the full ~3,500
TSX directory later by adding sources.

Writes `securities.issuers` in the hub `wtf` DB (same DB as the shared graph + parliament +
ec_contributions, so the Phase-1 reconcile is direct/set-based — no mesh hop). UPSERT only
(a thin/failed fetch never clobbers the existing directory).

Env:  WTF_DATABASE_URL
Run:  python -m ingest.securities_issuer_ingest --dry-run
      python -m ingest.securities_issuer_ingest
"""
import argparse
import html as _html
import logging
import os
import re

import requests
from sqlalchemy import create_engine, text

logger = logging.getLogger("securities.issuer_ingest")

_WIKI = "https://en.wikipedia.org/w/api.php"
# (page, index_label) — order matters only for the index_membership tag on first sighting.
_SOURCES = [("S&P/TSX 60", "TSX60"), ("S&P/TSX Composite Index", "TSX_COMPOSITE")]
_UA = {"User-Agent": "kytran-entity-graph/1.0 (Shared Entity Graph; research)"}

_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS securities;
CREATE TABLE IF NOT EXISTS securities.issuers (
    ticker            text PRIMARY KEY,
    name              text NOT NULL,
    exchange          text NOT NULL DEFAULT 'TSX',
    index_membership  text,
    source            text NOT NULL DEFAULT 'wikipedia',
    fetched_at        timestamptz NOT NULL DEFAULT now()
);
"""


def _engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


def _strip(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _parse_issuers(html_text):
    """Extract (name, ticker) from the constituents wikitables. A row contributes if it has
    a ticker-like cell (1-7 upper, '.'/'-' allowed) and a longer company-name cell."""
    out, seen = [], set()
    for tbl in re.findall(r"<table[\s\S]*?</table>", html_text):
        if "wikitable" not in tbl:
            continue
        for row in re.findall(r"<tr[\s\S]*?</tr>", tbl):
            cells = [c for c in (_strip(x) for x in re.findall(r"<t[dh][\s\S]*?</t[dh]>", row)) if c]
            if len(cells) < 2:
                continue
            ticker = next((c for c in cells if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", c)), None)
            name = next((c for c in cells if len(c) > 3 and re.search(r"[a-z]", c)
                         and re.search(r"[A-Za-z]{3,}", c)), None)
            if ticker and name and ticker not in seen:
                seen.add(ticker)
                out.append((name, ticker))
    return out


def fetch_tsx_issuers():
    """Returns [(name, ticker, index_membership)] deduped by ticker across the source pages."""
    rows, seen = [], set()
    for page, label in _SOURCES:
        try:
            r = requests.get(_WIKI, params={
                "action": "parse", "page": page, "prop": "text",
                "format": "json", "formatversion": "2"}, headers=_UA, timeout=30)
            r.raise_for_status()
            htmltext = (r.json().get("parse") or {}).get("text") or ""
        except Exception as exc:
            logger.warning("[securities] fetch %s failed: %s", page, exc)
            continue
        got = _parse_issuers(htmltext)
        logger.info("[securities] %s -> %d issuers", page, len(got))
        for name, ticker in got:
            if ticker not in seen:
                seen.add(ticker)
                rows.append((name, ticker, label))
    return rows


def run(dry_run=False):
    issuers = fetch_tsx_issuers()
    totals = {"fetched": len(issuers)}
    if len(issuers) < 50:
        # Defensive: a healthy TSX Composite fetch is ~220. Anything tiny = a broken
        # parse/blocked fetch -> do NOT write (upsert would still be safe, but bail loudly).
        logger.warning("[securities] only %d issuers fetched (<50) — skipping write", len(issuers))
        totals["skipped_thin_fetch"] = True
        return totals
    if dry_run:
        totals["dry_run"] = True
        logger.info("[securities] issuer ingest [dry-run]: %s", totals)
        return totals
    eng = _engine()
    with eng.begin() as conn:
        conn.execute(text(_SCHEMA_SQL))
        totals["upserted"] = conn.execute(text("""
            INSERT INTO securities.issuers (ticker, name, exchange, index_membership, source, fetched_at)
            VALUES (:ticker, :name, 'TSX', :idx, 'wikipedia', now())
            ON CONFLICT (ticker) DO UPDATE
              SET name = EXCLUDED.name,
                  index_membership = EXCLUDED.index_membership,
                  fetched_at = now()
        """), [{"name": n, "ticker": t, "idx": i} for (n, t, i) in issuers]).rowcount
    logger.info("[securities] issuer ingest done: %s", totals)
    return totals


def main():
    ap = argparse.ArgumentParser(description="TSX listed-issuer directory ingest (#373 Market L6 Phase 0)")
    ap.add_argument("--dry-run", action="store_true", help="fetch + count only, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
