"""cabinet.py — refresh parliament.mps.cabinet_role from an authoritative source.

Before this, cabinet_role was a manual static hand-seed with NO source and no
change history.  This module pulls the CURRENT federal ministry from the official
Prime Minister's site and reconciles it against parliament.mps:

  Source: https://www.pm.gc.ca/en/cabinet  (official, current-only, non-JS)
          Each minister is a clean card:
            <div class="name">The Honourable <Name></div>
            <div class="role"><Portfolio></div>
          → far cleaner than Wikipedia's ministry article, which is polluted
            with ~74 historical ministers and needs fragile section targeting.
          OpenParliament exposes NO cabinet/ministry data (checked: politician
          `memberships` are party+riding only) — so it cannot be the source.

  Matching: ministers are sitting MPs.  Name → parliament.mps by normalized full
          name, with a (first-token, last-token) fallback for middle initials /
          middle names and the "Right Honourable" PM prefix.  Live-verified 28/28
          current ministers matched (2026-07 read-only check).

  Deltas:  emits 'cabinet_change' movements (before/after cabinet_role) for
          added / changed / removed portfolios, and UPDATEs parliament.mps.

Fail-soft everywhere: a network error or an unrecognised page structure logs a
warning and returns without touching cabinet_role (never wipes on a bad scrape).

Env: WTF_DATABASE_URL   Run: python -m ingest.parliament.cabinet [--dry-run]
"""
import logging
import re
import sys
import unicodedata
from typing import Optional

import requests
from sqlalchemy import text

from ingest.parliament.openparl import record_movement

logger = logging.getLogger("wtf-ingest.cabinet")

_CABINET_URL = "https://www.pm.gc.ca/en/cabinet"
_HEADERS = {
    "User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)",
    "Accept": "text/html,application/xhtml+xml",
}
# If the scrape yields fewer than this, treat the page as changed/broken and
# do NOT reconcile (protects cabinet_role from a degraded response).
_MIN_MINISTERS = 5

_TITLE_PREFIXES = (
    "the right honourable ", "the honourable ", "honourable ", "hon. ", "hon ",
)


def _strip_title(name: str) -> str:
    low = name.lower()
    for pref in _TITLE_PREFIXES:
        if low.startswith(pref):
            return name[len(pref):]
    return name


def _norm(name: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse spaces."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[.'’-]", " ", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def _first_last(name: str) -> Optional[tuple]:
    toks = _norm(_strip_title(name)).split()
    return (toks[0], toks[-1]) if len(toks) >= 2 else None


# ── scrape ────────────────────────────────────────────────────────────────────

def fetch_ministers() -> list[tuple]:
    """Return [(minister_name, portfolio), ...] from pm.gc.ca, or [] on failure."""
    try:
        resp = requests.get(_CABINET_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("cabinet: fetch %s failed: %s", _CABINET_URL, exc)
        return []

    pairs = re.findall(
        r'<div class="name">\s*([^<]+?)\s*</div>\s*'
        r'<div class="role">\s*([^<]+?)\s*</div>',
        html, re.S,
    )
    out = []
    for raw_name, role in pairs:
        name = _strip_title(re.sub(r"\s+", " ", raw_name).strip())
        role = re.sub(r"\s+", " ", role).strip()
        if name and role:
            out.append((name, role))
    return out


# ── reconcile ───────────────────────────────────────────────────────────────

def refresh_cabinet(engine, dry_run: bool = False) -> dict:
    """Reconcile pm.gc.ca ministry against parliament.mps.cabinet_role.

    Returns stats: {fetched, matched, unmatched, added, changed, removed,
    movements}.  Caller (run.py) logs the summary to parliament.ingest_log.
    """
    ministers = fetch_ministers()
    stats = {"fetched": len(ministers), "matched": 0, "unmatched": [],
             "added": 0, "changed": 0, "removed": 0, "movements": 0}
    if len(ministers) < _MIN_MINISTERS:
        logger.warning(
            "cabinet: only %d ministers parsed (< %d) — page structure changed? "
            "skipping reconcile to protect cabinet_role", len(ministers), _MIN_MINISTERS)
        stats["error"] = "too_few_ministers"
        return stats

    # Load current MPs + their existing cabinet_role
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, slug, name, COALESCE(given_name,''), COALESCE(family_name,''), "
            "cabinet_role FROM parliament.mps WHERE is_current = true"
        )).fetchall()

    by_full: dict = {}
    by_fl: dict = {}
    current_role: dict = {}          # slug -> existing cabinet_role
    mp_by_slug: dict = {}            # slug -> (id, name)
    for mp_id, slug, name, gn, fn, cab in rows:
        mp_by_slug[slug] = (mp_id, name)
        current_role[slug] = cab
        by_full[_norm(name)] = slug
        toks = _norm(name).split()
        if len(toks) >= 2:
            by_fl.setdefault((toks[0], toks[-1]), slug)
        if gn and fn:
            by_fl.setdefault((_norm(gn).split()[0], _norm(fn).split()[-1]), slug)

    # Match ministers → slug, build desired cabinet {slug: role}
    desired: dict = {}
    for name, role in ministers:
        slug = by_full.get(_norm(_strip_title(name)))
        if not slug:
            fl = _first_last(name)
            slug = by_fl.get(fl) if fl else None
        if slug:
            desired[slug] = role
            stats["matched"] += 1
        else:
            stats["unmatched"].append(name)

    if stats["unmatched"]:
        logger.warning("cabinet: %d ministers unmatched to mps: %s",
                       len(stats["unmatched"]), stats["unmatched"])

    # Apply deltas: additions / changes
    for slug, new_role in desired.items():
        old_role = current_role.get(slug)
        if (old_role or "") == (new_role or ""):
            continue
        mp_id, mp_name = mp_by_slug[slug]
        if not dry_run:
            with engine.begin() as c:
                c.execute(text(
                    "UPDATE parliament.mps SET cabinet_role = :r, updated_at = NOW() "
                    "WHERE slug = :s"
                ), {"r": new_role, "s": slug})
                record_movement(c, "mp", "cabinet_change", subject_slug=slug,
                                 subject_id=mp_id, name=mp_name,
                                 before={"cabinet_role": old_role},
                                 after={"cabinet_role": new_role})
        stats["added" if not old_role else "changed"] += 1
        stats["movements"] += 1

    # Removals: had a cabinet_role, no longer in the ministry
    for slug, old_role in current_role.items():
        if not old_role or slug in desired:
            continue
        mp_id, mp_name = mp_by_slug[slug]
        if not dry_run:
            with engine.begin() as c:
                c.execute(text(
                    "UPDATE parliament.mps SET cabinet_role = NULL, updated_at = NOW() "
                    "WHERE slug = :s"
                ), {"s": slug})
                record_movement(c, "mp", "cabinet_change", subject_slug=slug,
                                 subject_id=mp_id, name=mp_name,
                                 before={"cabinet_role": old_role},
                                 after={"cabinet_role": None})
        stats["removed"] += 1
        stats["movements"] += 1

    logger.info("cabinet.refresh_cabinet: fetched=%d matched=%d added=%d changed=%d "
                "removed=%d movements=%d unmatched=%d%s",
                stats["fetched"], stats["matched"], stats["added"], stats["changed"],
                stats["removed"], stats["movements"], len(stats["unmatched"]),
                " (DRY-RUN)" if dry_run else "")
    return stats


def _get_engine():
    import os
    from sqlalchemy import create_engine
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url, pool_pre_ping=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry = "--dry-run" in sys.argv
    print(refresh_cabinet(_get_engine(), dry_run=dry))
