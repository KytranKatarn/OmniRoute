"""A.U.R.O.R.A. — Environment Canada public alerts (CAP 1.2).

Sibling of ingest/weather/citypage.py, same contract: a single never-raising
entry point, a heartbeat on EVERY path including the swallowed-error return,
and a task name that matches drift_guard._MAX_AGE_DAYS.

ADR-001: dd.weather.gc.ca ONLY (same host as citypage/cwfis/aqhi).

PATH — verified live 2026-09-06 (Dev HQ #6621 item 5):
    https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/alerts/cap/{YYYYMMDD}/
        {office_code}/{HH}/{filename}.cap
  · Same dated-root-then-hour-directory shape as citypage. {office_code} is
    an ECCC weather-office code (CWHX, CWNT, CWUL, CWWG, LAND — 5 total,
    verified live) — NOT a province code and NOT a 1:1 province mapping (one
    office issues alerts across several provinces). Do NOT invent an
    office->province table: the real geographic scope is carried IN each
    alert (see below), which is the honest source, not an inference.
  · Payload is standard CAP 1.2 XML, namespaced
    urn:oasis:names:tc:emergency:cap:1.2. A single file often carries TWO
    sibling <info> blocks (en-CA and fr-CA) — this ingest keeps only the
    English one, matching every other page on this site.
  · The real geographic scope of an alert is NOT the office code — it's two
    real fields already in the payload: the "Alert_Coverage" <parameter>
    (a plain-English province/region name, e.g. "Nova Scotia") and
    <area><areaDesc> (a finer county/zone name, e.g. "Victoria County").
    Both are stored as free text and shown as-is — no attempt to
    canonicalise "Nova Scotia" against consumer/aurora_map.py's 2-letter
    _canon_prov codes, since that function's whole contract is normalizing
    SHORT CODES from OTHER feeds, not province names from CAP text.
  · "Is this alert still live" is NOT stored as a boolean — it's computed at
    query time (routes.py) from status/location_status/expires_utc, the same
    "never bake in a derived truth that a clock can silently invalidate"
    principle already used elsewhere in this ingest tree (e.g. drift_guard's
    age-in-SQL pattern).
"""
import datetime
import logging
import os
import re
import urllib.request
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from sqlalchemy import text

logger = logging.getLogger(__name__)

_BASE = "https://dd.weather.gc.ca"
_UA = {"User-Agent": "archie-aurora/1.0 (what-the-fact.com; weather ingest)"}
_TIMEOUT = int(os.environ.get("AURORA_ALERTS_HTTP_TIMEOUT", "25"))
_CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
# How many hour-directories back to look, same reasoning as citypage: a
# quiet office for an hour or two is normal, not an error, and re-fetching a
# few hours back costs nothing because every upsert is keyed on the CAP
# <identifier>, which is globally unique per alert — re-seeing one is a
# guaranteed no-op, never a duplicate.
_HOUR_LOOKBACK = int(os.environ.get("AURORA_ALERTS_HOUR_LOOKBACK", "6"))


def _fetch(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — fixed public host
        return r.status, r.read()


def _list_dir(url):
    """Relative subdirectory or file names in an Apache autoindex listing.
    [] on any failure — a missing hour/office directory is normal, not an
    error (an office with nothing to say simply has no dir for that hour)."""
    try:
        st, body = _fetch(url)
    except Exception as exc:  # noqa: BLE001 — an absent dir is expected
        logger.debug("alerts: listing %s failed: %s", url, exc)
        return []
    if st != 200:
        return []
    return body.decode("utf-8", "replace")


def _rel_entries(html, suffix=None):
    if suffix:
        return re.findall(r'href="([^"/][^"]*%s)"' % re.escape(suffix), html)
    return [h.rstrip("/") for h in re.findall(r'href="([^"/][^"]*)/"', html)]


def _offices_for_date(date_str):
    html = _list_dir("%s/%s/WXO-DD/alerts/cap/%s/" % (_BASE, date_str, date_str))
    return _rel_entries(html) if html else []


def _files_for_office_hour(date_str, office, hour):
    html = _list_dir("%s/%s/WXO-DD/alerts/cap/%s/%s/%s/" % (
        _BASE, date_str, date_str, office, hour))
    return _rel_entries(html, suffix=".cap") if html else []


def _tag(elem, name):
    """Namespace-qualified child text, or None. CAP files are always in the
    single urn:oasis:names:tc:emergency:cap:1.2 namespace — no version
    negotiation needed, this site has only ever seen 1.2 live."""
    child = elem.find("{%s}%s" % (_CAP_NS, name))
    return child.text if child is not None and child.text else None


def _parse_cap(raw, fname):
    """One .cap file -> a row dict, or None on any shape surprise. Never
    raises — a single malformed file must not stop the office/hour."""
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        # DefusedXmlException covers entity-expansion/DTD attacks — a
        # malicious or malformed file is the same "skip this one, don't
        # stop the office/hour" case either way.
        logger.debug("alerts: XML parse failed for %s: %s", fname, exc)
        return None

    identifier = _tag(root, "identifier")
    if not identifier:
        return None

    # Pick the English <info> block. A file commonly carries en-CA + fr-CA
    # siblings; some carry only one. Never guess a language — check it.
    infos = root.findall("{%s}info" % _CAP_NS)
    info = None
    for i in infos:
        lang = _tag(i, "language") or ""
        if lang.lower().startswith("en"):
            info = i
            break
    if info is None and infos:
        # No block was tagged en-* at all — genuinely ambiguous. Skip rather
        # than guess which language the headline/description are in.
        return None
    if info is None:
        return None

    coverage_name = None
    location_status = None
    for p in info.findall("{%s}parameter" % _CAP_NS):
        vn = _tag(p, "valueName") or ""
        val = _tag(p, "value")
        if vn.endswith(":Alert_Coverage"):
            coverage_name = val
        elif vn.endswith(":Alert_Location_Status"):
            location_status = val

    area = info.find("{%s}area" % _CAP_NS)
    area_desc = _tag(area, "areaDesc") if area is not None else None

    return {
        "identifier": identifier,
        "office_code": None,  # filled by caller (known from the directory path, not the payload)
        "status": _tag(root, "status"),
        "msg_type": _tag(root, "msgType"),
        "event": _tag(info, "event"),
        "urgency": _tag(info, "urgency"),
        "severity": _tag(info, "severity"),
        "certainty": _tag(info, "certainty"),
        "headline": _tag(info, "headline"),
        "description": _tag(info, "description"),
        "coverage_name": coverage_name,
        "area_desc": area_desc,
        "location_status": location_status,
        "sent_utc": _tag(root, "sent"),
        "effective_utc": _tag(info, "effective"),
        "expires_utc": _tag(info, "expires"),
        "source_file": fname,
    }


def _run_alerts(engine, dry_run):
    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%Y%m%d")
    stats = {"offices": 0, "fetched": 0, "upserted": 0, "parse_error": 0}
    rows = []

    offices = _offices_for_date(date_str)
    stats["offices"] = len(offices)
    for office in offices:
        for back in range(_HOUR_LOOKBACK):
            t = now - datetime.timedelta(hours=back)
            hour = t.strftime("%H")
            fnames = _files_for_office_hour(date_str, office, hour)
            for fname in fnames:
                st, raw = _fetch("%s/%s/WXO-DD/alerts/cap/%s/%s/%s/%s" % (
                    _BASE, date_str, date_str, office, hour, fname))
                if st != 200:
                    stats["parse_error"] += 1
                    continue
                row = _parse_cap(raw, fname)
                if row is None:
                    stats["parse_error"] += 1
                    continue
                row["office_code"] = office
                stats["fetched"] += 1
                rows.append(row)

    if dry_run:
        stats["upserted"] = len(rows)
        return stats

    if not rows and stats["offices"] == 0:
        return {"error": "no alert offices listed for %s — path shape may have changed" % date_str}

    with engine.begin() as c:
        for row in rows:
            result = c.execute(text("""
                INSERT INTO wtf.aurora_alerts
                    (identifier, office_code, status, msg_type, event, urgency,
                     severity, certainty, headline, description, coverage_name,
                     area_desc, location_status, sent_utc, effective_utc,
                     expires_utc, source_file)
                VALUES (:identifier, :office_code, :status, :msg_type, :event, :urgency,
                        :severity, :certainty, :headline, :description, :coverage_name,
                        :area_desc, :location_status, :sent_utc, :effective_utc,
                        :expires_utc, :source_file)
                ON CONFLICT (identifier) DO UPDATE SET
                    status = EXCLUDED.status, msg_type = EXCLUDED.msg_type,
                    location_status = EXCLUDED.location_status,
                    headline = EXCLUDED.headline, description = EXCLUDED.description,
                    expires_utc = EXCLUDED.expires_utc, fetched_at = now()
            """), row)
            if result.rowcount > 0:
                stats["upserted"] += 1
    return stats


def _heartbeat(engine, task, result, exc):
    """parliament.ingest_log on BOTH paths — same never-silent contract as
    citypage.py/aqhi.py/boc_rates.py."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"),
                    {"t": task, "f": int(result.get("fetched") or 0),
                     "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001 — a heartbeat must never break the ingest
        logger.exception("alerts: heartbeat write failed for %s", task)


def run_aurora_alerts(engine, dry_run=False):
    """Entry point. NEVER raises — returns a per-run summary dict, same
    contract as run_aurora_citypage/run_aurora_cwfis/run_aurora_aqhi."""
    task = "aurora_alerts"
    try:
        res = _run_alerts(engine, dry_run)
        if not dry_run:
            _heartbeat(engine, task, res, None)
        return res
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s crashed", task)
        if not dry_run:
            _heartbeat(engine, task, {}, exc)
        return {"error": str(exc)}


if __name__ == "__main__":
    import sys
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_aurora_alerts(eng, dry_run="--dry-run" in sys.argv))
