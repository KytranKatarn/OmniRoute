"""lobbying.py — Lobbying registry ingest from lobbycanada.gc.ca bulk export.

lobbycanada.gc.ca sits behind a Cloudflare INTERACTIVE Turnstile (since ~June
2026): plain urllib 403s, Chrome-impersonated TLS (curl_cffi) 403s (clearance
is cookie-gated, not just JA3), and HEADLESS Chrome never clears the challenge.
What works — verified live 2026-08-18 — is headed Chrome under Xvfb with a
programmatic mouse click inside the turnstile iframe. The ZIP is therefore
fetched on the HUB by the weekly parliament cron (scripts/senate_votes_cron.sh,
xvfb-run), like senators/senate_votes. The ingest container's weekly attempt
had been returning {'error': 403} silently — lobbying is now HUB-OWNED and is
no longer in the container's phase-3 task list.

The download page's ZIP link is scraped live (a[href*='.zip'] on
/en/open-data/), so the hash-slugged /media/ URL rotating no longer breaks the
feed either.

Full-history replace: the export carries every communication since 2008, so a
successful run atomically DELETEs + re-INSERTs parliament.lobbyist_contacts.
That also retires the old family-name-only MP matcher, which silently
mis-attributed ~3,573 contacts inside ambiguous families (parliament.mps holds
SEVEN current MPs surnamed Gill) — replaced by the same 3-tier index ethics
uses (exact → dot-stripped first+last → unique-family, ALL MPs, current wins).

Run (hub): xvfb-run -a python3 -m ingest.parliament.lobbying [--dry-run]
"""
import csv
import io
import logging
import os
import urllib.request
import zipfile
from datetime import date

from sqlalchemy import create_engine, text

from ingest.parliament.ethics_disclosures import _build_mp_index, _match_mp

logger = logging.getLogger("wtf-ingest.lobbying")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_OPEN_DATA_URL = "https://lobbycanada.gc.ca/en/open-data/"
# Direct URL kept as a fallback probe only — the page scrape above is canonical.
_COMMS_ZIP = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
_HEADERS = {"User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)"}
_PROFILE_DIR = os.path.expanduser("~/.cache/wtf_lobby_profile")

_MP_TITLES = {
    "member of parliament", "mp", "député", "députée",
    "member of parliment",  # typo in registry
    "member of the house of commons",
}
_INSERT_BATCH = 5000


def _download_zip(url: str) -> bytes:
    """Plain urllib fetch — 403s behind the turnstile; kept for the day the
    wall comes down (and as the honest failure path in the container)."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _clear_turnstile(page, tries: int = 4) -> bool:
    """Clear Cloudflare's interactive Turnstile by clicking inside its iframe.

    Headed Chrome only — in headless mode the challenge never presents a
    passable checkbox (measured: title stays 'Just a moment...' forever)."""
    for _ in range(tries):
        if "Just a moment" not in page.title():
            return True
        clicked = False
        for f in page.frames:
            if "challenges.cloudflare.com" in f.url:
                try:
                    box = f.frame_element().bounding_box()
                    if box:
                        page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
                        clicked = True
                except Exception:
                    pass
        page.wait_for_timeout(4000 if clicked else 2500)
        for _ in range(10):
            if "Just a moment" not in page.title():
                return True
            page.wait_for_timeout(1500)
    return "Just a moment" not in page.title()


def fetch_comms_zip_via_browser() -> bytes:
    """Headed-Chrome fetch of the communications ZIP (hub, under xvfb-run).

    Scrapes the ZIP link off the open-data page (self-heals /media/ slug
    rotation), clears the turnstile, and captures the browser download.
    Raises on any failure — the caller writes the error heartbeat."""
    from playwright.sync_api import sync_playwright

    os.makedirs(_PROFILE_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            _PROFILE_DIR,
            executable_path="/usr/bin/google-chrome",
            headless=False,                       # headless cannot clear the turnstile
            accept_downloads=True,
            locale="en-CA",
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1366, "height": 768},
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(60000)
            page.goto(_OPEN_DATA_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if not _clear_turnstile(page):
                raise RuntimeError("Cloudflare turnstile did not clear (page stuck at 'Just a moment...')")
            links = page.eval_on_selector_all('a[href*=".zip"]', "els => els.map(e => e.href)")
            comms = [l for l in links if "communications" in l]
            if not comms:
                raise RuntimeError(f"no communications ZIP link on {_OPEN_DATA_URL} (links={links[:4]})")
            with page.expect_download(timeout=300000) as dl:
                page.evaluate(
                    "url => { const a = document.createElement('a'); a.href = url;"
                    " a.download = ''; document.body.appendChild(a); a.click(); }",
                    comms[0])
            tmp_path = dl.value.path()
            raw = open(tmp_path, "rb").read()
        finally:
            ctx.close()
    if raw[:2] != b"PK":
        raise RuntimeError(f"downloaded file is not a ZIP (magic={raw[:4]!r}, {len(raw)} bytes)")
    logger.info("lobbying: browser download OK (%d KB)", len(raw) // 1024)
    return raw


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


def run_lobbying_sync(engine, zip_bytes: bytes | None = None, dry_run: bool = False) -> dict:
    """Parse the communications export and REPLACE parliament.lobbyist_contacts.

    zip_bytes=None tries the plain urllib fetch (403s behind the wall — the
    container's honest failure). The hub entrypoint passes browser-fetched
    bytes. dry_run parses + matches but writes nothing."""
    if zip_bytes is None:
        logger.info("lobbying: downloading communications ZIP (%s)", _COMMS_ZIP)
        try:
            zip_bytes = _download_zip(_COMMS_ZIP)
        except Exception as exc:
            logger.error("lobbying: download failed: %s", exc)
            return {"error": str(exc)}

    logger.info("lobbying: parsing ZIP (%d KB)", len(zip_bytes) // 1024)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        primary = _read_csv(zf, "Communication_PrimaryExport.csv")
        dpoh = _read_csv(zf, "Communication_DpohExport.csv")

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

    mp_dpoh = [
        row for row in dpoh
        if "House of Commons" in row.get("INSTITUTION", "")
        and row.get("DPOH_TITLE_TITRE_TCPD", "").lower() in _MP_TITLES
    ]
    logger.info("lobbying: %d MP-level DPOH contacts found", len(mp_dpoh))

    exact, token, family = _build_mp_index(engine)

    rows: dict[tuple, dict] = {}   # (comlog_id, mp_id) -> params; dedups exact pairs
    unmatched = 0
    skipped = 0
    for dpoh_row in mp_dpoh:
        cid = dpoh_row.get("COMLOG_ID", "").strip()
        pri = primary_idx.get(cid)
        if not cid or pri is None:
            skipped += 1
            continue
        name_raw = (f"{dpoh_row.get('DPOH_FIRST_NM_PRENOM_TCPD', '')} "
                    f"{dpoh_row.get('DPOH_LAST_NM_TCPD', '')}")
        mp_id = _match_mp(name_raw, exact, token, family)
        if not mp_id:
            unmatched += 1
            continue
        try:
            comm_date = date.fromisoformat(pri["comm_date"]) if pri["comm_date"] else None
        except ValueError:
            comm_date = None
        rows[(cid, mp_id)] = {
            "mp_id": mp_id, "cid": cid,
            "ll": pri["lobbyist_last"], "lf": pri["lobbyist_first"],
            "org": pri["client_org"], "dt": comm_date,
        }

    result = {"fetched": len(mp_dpoh), "matched": len(rows),
              "unmatched": unmatched, "skipped": skipped}
    if dry_run:
        logger.info("lobbying DRY RUN: %s", result)
        return result

    # Atomic full replace — the export is complete history, and replacement is
    # the only way stale mis-attributions (old family-only matcher) leave the
    # table. Readers see the old set until commit.
    params = list(rows.values())
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.lobbyist_contacts"))
        for i in range(0, len(params), _INSERT_BATCH):
            c.execute(text("""
                INSERT INTO parliament.lobbyist_contacts
                    (mp_id, comlog_id, lobbyist_last, lobbyist_first,
                     client_org, communication_date)
                VALUES (:mp_id, :cid, :ll, :lf, :org, :dt)
                ON CONFLICT (comlog_id, mp_id) DO NOTHING
            """), params[i:i + _INSERT_BATCH])
    result["inserted"] = len(params)
    logger.info("lobbying: replaced table — %s", result)
    return result


def run_lobbying_sync_hub(dry_run: bool = False) -> dict:
    """Browser fetch + sync + a parliament.ingest_log heartbeat either way.

    HUB entrypoint (weekly cron, xvfb-run). drift_guard watches the
    'lobbying' task; before 2026-08-18 the feed had been dead 60+ days with
    the container swallowing {'error': 403} as a quiet success."""
    engine = create_engine(os.environ["WTF_DATABASE_URL"])
    try:
        raw = fetch_comms_zip_via_browser()
        stats = run_lobbying_sync(engine, zip_bytes=raw, dry_run=dry_run)
        if stats.get("error"):
            raise RuntimeError(stats["error"])
        if not dry_run:
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES ('lobbying', :f, :u)"),
                    {"f": int(stats.get("fetched") or 0),
                     "u": int(stats.get("inserted") or 0)})
        return stats
    except Exception as exc:
        try:
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES ('lobbying', :e)"),
                    {"e": str(exc)[:500]})
        except Exception:
            logger.exception("lobbying heartbeat write failed")
        raise


if __name__ == "__main__":
    import sys
    run_lobbying_sync_hub(dry_run="--dry-run" in sys.argv)
