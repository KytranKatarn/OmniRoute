"""elections_canada.py — Political contribution data from Elections Canada Open Data.

Downloads od_cntrbtn_de_e.zip (~201MB), streams the CSV, and bulk-imports all
contributions from 2019+ into parliament.ec_contributions.

Scope: 43rd (2019), 44th (2021), 45th (2025) Parliaments ≈ 4.1M rows.
After import, two SQL views provide riding-level and party-level summaries
that are used on the MP profile pages and the party transparency page.

Design:
- TRUNCATE + re-import on each sync (file updated quarterly, full refresh
  is correct — no dedup key exists across all row types in the EC format)
- Stream CSV row by row to avoid memory spike (10M rows, 201MB uncompressed)
- Batch commits every 10,000 rows for throughput + rollback safety
- Zip cached for 30 days at WTF_EC_CACHE_PATH (default /tmp/ec_contributions.zip)

Env:
    WTF_EC_MIN_YEAR    2019    import rows where Fiscal/Election date >= this year
    WTF_EC_CACHE_PATH  /tmp/ec_contributions.zip    local zip cache path
    WTF_EC_CACHE_DAYS  30      skip re-download if cache is fresher than this

Column index reference (27 columns):
  0  Political Entity
  1  Recipient ID
  2  Recipient
  6  Political Party of Recipient
  7  Electoral District
  8  Electoral event
  9  Fiscal/Election date
  10 Form ID
  14 Contributor type
  15 Contributor name
  19 Contributor City
  20 Contributor Province
  21 Contributor Postal code
  22 Contribution Received date
  23 Monetary amount
  24 Non-Monetary amount
"""
import csv
import io
import logging
import os
import re
import shutil
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.parliament")

_EC_URL = "https://www.elections.ca/fin/oda/od_cntrbtn_de_e.zip"
_EC_CSV = "PoliticalFinance/od_cntrbtn_de_e.csv"
_UA = "WTFIngest/1.0 (+https://what-the-fact.com)"
_DL_TIMEOUT = int(os.environ.get("WTF_EC_DL_TIMEOUT", "600"))  # ~202MB over a slow link
_MIN_YEAR = int(os.environ.get("WTF_EC_MIN_YEAR", "2019"))
_CACHE_PATH = os.environ.get("WTF_EC_CACHE_PATH", "/tmp/ec_contributions.zip")
_CACHE_DAYS = int(os.environ.get("WTF_EC_CACHE_DAYS", "30"))
_BATCH_SIZE = 10_000


def _cache_is_fresh() -> bool:
    if not os.path.exists(_CACHE_PATH):
        return False
    age_days = (time.time() - os.path.getmtime(_CACHE_PATH)) / 86400
    return age_days < _CACHE_DAYS


def _find_csv_member(zf: "zipfile.ZipFile"):
    """Locate the contributions CSV inside the zip — the known path if present, else the largest
    .csv member (tolerant of Elections Canada renaming the internal path)."""
    names = zf.namelist()
    if _EC_CSV in names:
        return _EC_CSV
    csvs = [n for n in names if n.lower().endswith(".csv")]
    return max(csvs, key=lambda n: zf.getinfo(n).file_size) if csvs else None


def _is_valid_zip(path: str) -> bool:
    """True iff `path` is a readable zip that actually contains a CSV member — the guard that
    stops a truncated download or an HTML error page from being cached and reused as if it were
    the data (the stale-cache trap that silently failed this ingest for weeks)."""
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return _find_csv_member(zf) is not None
    except (zipfile.BadZipFile, OSError):
        return False


def _download_zip() -> None:
    """Fetch the EC contributions zip to the cache, VALIDATED. A fresh, valid cache is reused; a
    stale OR corrupt cache is deleted (never reused); a download that isn't a complete, valid zip
    is rejected and never cached. Uses urlopen(Request) so the User-Agent is actually sent (the
    old urlretrieve silently dropped it)."""
    if _cache_is_fresh() and _is_valid_zip(_CACHE_PATH):
        logger.info("ec_contributions: using cached zip (%s)", _CACHE_PATH)
        return
    if os.path.exists(_CACHE_PATH):   # stale or corrupt — drop it, never reuse a bad file
        try:
            os.remove(_CACHE_PATH)
        except OSError:
            pass

    tmp = _CACHE_PATH + ".tmp"
    logger.info("ec_contributions: downloading %s → %s", _EC_URL, _CACHE_PATH)
    req = urllib.request.Request(_EC_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_DL_TIMEOUT) as r:
        expected = int(r.headers.get("Content-Length") or 0)
        with open(tmp, "wb") as out:
            shutil.copyfileobj(r, out, length=1 << 20)
    got = os.path.getsize(tmp)

    # integrity gates — never promote a bad file into the cache
    if expected and got != expected:
        os.remove(tmp)
        raise IOError(
            "ec_contributions: truncated download (%d of %d bytes) — not cached" % (got, expected)
        )
    if not _is_valid_zip(tmp):
        os.remove(tmp)
        raise IOError(
            "ec_contributions: download is not a valid zip with a CSV member (%d bytes) — not "
            "cached (URL blocked / HTML error page / truncated?)" % got
        )
    os.rename(tmp, _CACHE_PATH)
    logger.info("ec_contributions: download complete + validated (%dMB)", got // 1_000_000)


def _parse_amount(s: str) -> Optional[float]:
    try:
        return float(s.strip()) if s and s.strip() else None
    except ValueError:
        return None


_EC_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_REJECTS = {"n": 0}  # per-run tally, logged + reset in sync_contributions


# A contribution's date is when it was RECEIVED, so it cannot be in the future. The slack only covers clock skew and a
# filing dated a few days ahead. It was 366 days, which let through monthly-instalment-looking rows dated up to 11 months
# ahead (44 rows, $9.5K, measured 2026-10-07): the riding donor panel then showed an "Annual 2027" line for money that
# cannot have been received yet.
_MAX_FUTURE_DAYS = 31


def _parse_date(s: str, today: Optional[date] = None) -> Optional[str]:
    s = (s or "").strip()[:10]
    if not s:
        return None
    # EC dates are YYYY-MM-DD — but the source CSVs carry artifacts (prod
    # held 0025-04-07, 0201-02-16 and 551 future rows up to 2923-12-28,
    # measured 2026-08-18). Guard impossible values the way gov-watch's
    # date_guard does: store NULL instead of garbage — the weekly
    # TRUNCATE+reimport then self-heals the whole table. Bounds are loose
    # on purpose: 1990 predates EC's electronic era; +31d (see _MAX_FUTURE_DAYS) allows
    # for skew without admitting year-2923 artifacts.
    if not _EC_DATE_RE.match(s) or s < "1990-01-01" \
            or s > ((today or date.today()) + timedelta(days=_MAX_FUTURE_DAYS)).isoformat():
        _DATE_REJECTS["n"] += 1
        return None
    return s


_INSERT_SQL = """
    INSERT INTO parliament.ec_contributions
        (political_entity, recipient_name, party, electoral_district,
         electoral_event, election_date, form_id, contributor_type,
         contributor_name, contributor_city, contributor_province,
         contributor_postal, contribution_date, monetary_amount,
         non_monetary_amount)
    VALUES %s
"""


def sync_contributions(engine) -> dict:
    """Download, stream, and bulk-import EC contributions into parliament.ec_contributions.

    Uses psycopg2 execute_values for ~50x faster bulk inserts vs parameterized SQL.
    Always does a full TRUNCATE + re-import. Runs ~5-10 min for 4M rows.
    """
    import psycopg2.extras

    _download_zip()

    zf = zipfile.ZipFile(_CACHE_PATH)
    member = _find_csv_member(zf)
    if member is None:
        raise IOError("ec_contributions: no CSV member in the zip (members=%s)" % zf.namelist()[:5])
    inserted = 0
    skipped = 0
    batch = []

    raw_conn = engine.raw_connection()
    try:
        # TRUNCATE before import — always full refresh
        cur = raw_conn.cursor()
        cur.execute("TRUNCATE parliament.ec_contributions RESTART IDENTITY")
        raw_conn.commit()
        logger.info("ec_contributions: truncated, streaming CSV...")

        with zf.open(member) as raw:
            text_file = io.TextIOWrapper(raw, encoding="utf-8-sig")
            reader = csv.reader(text_file)
            next(reader)  # skip header

            for row in reader:
                if len(row) < 25:
                    skipped += 1
                    continue

                # Filter by year
                date_str = row[9].strip()
                year_str = date_str[:4] if date_str else ""
                if not year_str.isdigit() or int(year_str) < _MIN_YEAR:
                    skipped += 1
                    continue

                entity = row[0].strip().lstrip("﻿")
                batch.append((
                    entity,
                    (row[2] or "")[:500],
                    (row[6] or "")[:200],
                    (row[7] or "")[:200],
                    (row[8] or "")[:200],
                    _parse_date(row[9]),
                    (row[10] or "")[:100],
                    (row[14] or "")[:100],
                    (row[15] or "")[:500],
                    (row[19] or "")[:200],
                    (row[20] or "")[:2] or None,
                    (row[21] or "")[:10],
                    _parse_date(row[22]),
                    _parse_amount(row[23]),
                    _parse_amount(row[24]),
                ))

                if len(batch) >= _BATCH_SIZE:
                    psycopg2.extras.execute_values(cur, _INSERT_SQL, batch,
                                                   page_size=_BATCH_SIZE)
                    raw_conn.commit()
                    inserted += len(batch)
                    batch = []
                    if inserted % 500_000 == 0:
                        logger.info("ec_contributions: %d rows inserted...", inserted)

            if batch:
                psycopg2.extras.execute_values(cur, _INSERT_SQL, batch,
                                               page_size=len(batch))
                raw_conn.commit()
                inserted += len(batch)

    finally:
        raw_conn.close()

    rejected_dates = _DATE_REJECTS["n"]
    _DATE_REJECTS["n"] = 0
    if rejected_dates:
        # A silent discard is how the garbage got in — a JUMP in this count
        # means the upstream CSV format changed, not that the guard is wrong.
        logger.warning("ec_contributions: %d impossible dates stored as NULL", rejected_dates)
    logger.info("ec_contributions: done — inserted=%d skipped=%d date_rejects=%d",
                inserted, skipped, rejected_dates)
    return {"inserted": inserted, "skipped": skipped, "date_rejects": rejected_dates}


def run_ec_sync(engine) -> dict:
    """Entry point called from run_parliament_sync() weekly on Sundays.

    Runs after sync_mps/sync_votes/sync_ballots so MPs are already in DB.
    """
    start = datetime.now(timezone.utc)
    try:
        result = sync_contributions(engine)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        result["elapsed_s"] = round(elapsed, 1)
        logger.info("ec sync complete in %.1fs: %s", elapsed, result)
        with engine.begin() as c:
            c.execute(text("""
                INSERT INTO parliament.ingest_log
                    (task, records_fetched, records_upserted)
                VALUES ('ec_contributions', :f, :u)
            """), {"f": result["inserted"] + result["skipped"],
                   "u": result["inserted"]})
        return result
    except Exception as exc:
        logger.exception("ec_contributions sync failed: %s", exc)
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO parliament.ingest_log (task, error) VALUES ('ec_contributions', :e)"
            ), {"e": str(exc)[:500]})
        return {"error": str(exc)}
