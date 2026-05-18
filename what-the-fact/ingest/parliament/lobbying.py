"""lobbying.py — Lobbying registry ingest from lobbycanada.gc.ca bulk export.

Downloads the Communications ZIP (~22MB), joins Primary + DPOH exports,
filters contacts at the House of Commons with MP titles, fuzzy-matches
family names against parliament.mps, and upserts into
parliament.lobbyist_contacts.

Runs weekly from run_parliament_sync(). Idempotent (ON CONFLICT DO NOTHING).
"""
import csv
import io
import logging
import time
import urllib.request
import zipfile

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.lobbying")

_COMMS_ZIP = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
_SUBJ_ZIP = "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip"
_HEADERS = {"User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)"}

_MP_TITLES = {
    "member of parliament", "mp", "député", "députée",
    "member of parliment",  # typo in registry
    "member of the house of commons",
}

_ALLOWED_SCHEMAS = frozenset({"parliament"})


def _download_zip(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    with zf.open(name) as f:
        text_content = f.read().decode("cp1252")
    reader = csv.reader(io.StringIO(text_content))
    headers = [h.strip() for h in next(reader)]
    return [
        {h: v.strip() for h, v in zip(headers, row)}
        for row in reader
        if any(v.strip() for v in row)
    ]


def run_lobbying_sync(engine) -> dict:
    """Download lobbying communications data and insert MP contacts."""
    logger.info("lobbying: downloading communications ZIP (%s)", _COMMS_ZIP)
    try:
        raw = _download_zip(_COMMS_ZIP)
    except Exception as exc:
        logger.error("lobbying: download failed: %s", exc)
        return {"error": str(exc)}

    logger.info("lobbying: parsing ZIP (%d KB)", len(raw) // 1024)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        primary = _read_csv(zf, "Communication_PrimaryExport.csv")
        dpoh = _read_csv(zf, "Communication_DpohExport.csv")

    # Build primary index: comlog_id → {lobbyist, org, date}
    primary_idx: dict[str, dict] = {}
    for row in primary:
        cid = row.get("COMLOG_ID", "").strip()
        if not cid:
            continue
        primary_idx[cid] = {
            "lobbyist_last": row.get("RGSTRNT_LAST_NM_DCLRNT", ""),
            "lobbyist_first": row.get("RGSTRNT_1ST_NM_PRENOM_DCLRNT", ""),
            "client_org": row.get("EN_CLIENT_ORG_CORP_NM_AN", ""),
            "comm_date": row.get("COMM_DATE", ""),
        }

    # Filter DPOH rows to House of Commons MPs only
    mp_dpoh = [
        row for row in dpoh
        if "House of Commons" in row.get("INSTITUTION", "")
        and row.get("DPOH_TITLE_TITRE_TCPD", "").lower() in _MP_TITLES
    ]
    logger.info("lobbying: %d MP-level DPOH contacts found", len(mp_dpoh))

    # Load MP family names from DB
    with engine.connect() as c:
        mp_rows = c.execute(text(
            "SELECT id, family_name, name FROM parliament.mps WHERE is_current = true"
        )).fetchall()
    # Build index: lowercase family name → mp_id
    family_idx: dict[str, int] = {}
    for row in mp_rows:
        fn = (row[1] or "").strip().lower()
        if fn:
            family_idx[fn] = row[0]

    inserted = 0
    skipped = 0
    for dpoh_row in mp_dpoh:
        cid = dpoh_row.get("COMLOG_ID", "").strip()
        if not cid or cid not in primary_idx:
            skipped += 1
            continue

        dpoh_last = dpoh_row.get("DPOH_LAST_NM_TCPD", "").strip().lower()
        mp_id = family_idx.get(dpoh_last)
        if not mp_id:
            skipped += 1
            continue

        pri = primary_idx[cid]
        comm_date_str = pri.get("comm_date", "")
        try:
            from datetime import date
            comm_date = date.fromisoformat(comm_date_str) if comm_date_str else None
        except ValueError:
            comm_date = None

        try:
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.lobbyist_contacts
                        (mp_id, comlog_id, lobbyist_last, lobbyist_first,
                         client_org, communication_date)
                    VALUES (:mp_id, :cid, :ll, :lf, :org, :dt)
                    ON CONFLICT (comlog_id, mp_id) DO NOTHING
                """), {
                    "mp_id": mp_id,
                    "cid": cid,
                    "ll": pri["lobbyist_last"],
                    "lf": pri["lobbyist_first"],
                    "org": pri["client_org"],
                    "dt": comm_date,
                })
            inserted += 1
        except Exception as exc:
            logger.debug("lobbying: insert failed cid=%s: %s", cid, exc)
            skipped += 1

    logger.info("lobbying: inserted=%d skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}
