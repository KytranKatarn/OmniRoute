"""A.U.R.O.R.A. — evacuation-order layer (Dev HQ #6624).

Two independent pipelines, one file, same never-raising contract as every
other ingest in this tree (a heartbeat on EVERY path, a task name matching
drift_guard._MAX_AGE_DAYS/_REQUIRED_TASKS).

Scope decided by live research 2026-09-06 (decision #1082/#1083): the
original framing assumed no single national source existed and proposed a
province-by-province patchwork. A real one does — NAAD/Alert Ready, the same
CAP-CP infrastructure behind Canada's wireless/broadcast emergency alerts —
plus BC publishes its own genuinely evacuation-SPECIFIC structured feed
(explicit Order-vs-Alert status) richer than free-text CAP. Alberta/Ontario/
Quebec do NOT get their own pipeline: Alberta's feed is real but redundant
with NAAD (NAAD already carries Alberta-issued alerts); Ontario has no
provincial API of its own; Quebec's apparent one
(qea-api.int.geo.msp.gouv.qc.ca) is confirmed NXDOMAIN on public DNS —
internal-only by design, not merely undocumented.

1. NAAD/Alert Ready (run_aurora_evacuations_naad)
   Live index: https://rss.naad-adna.pelmorex.com/ (Atom+GeoRSS; mirror
   rss1...) — each <entry> links to the full CAP-CP 1.2 XML at
   capcp1/capcp2.naad-adna.pelmorex.com/<date>/<file>.xml. No auth, no key.

   CAP-CP has NO distinct "evacuation" event/category value — an evacuation
   order arrives tagged under whatever triggering hazard (Wildfire, Flood,
   Civil Emergency, ...) with the actual instruction as free text inside
   <description>/<instruction>. So classification is BOTH an event allowlist
   AND a keyword pass — never one alone:
     - event allowlist rules out AMBER/Silver Alert, weather-only warnings,
       Air Quality, etc. by construction (those events never reach the
       keyword check at all)
     - the keyword check is a WORD-BOUNDARY regex, not a bare substring —
       "vacuuming" must never match. See _EVAC_RE_EN/_EVAC_RE_FR and
       test_evacuation_keyword_regex.py for the proof.
   Only alerts passing BOTH are stored; matched_keyword records which
   pattern actually hit, for auditability (a human should be able to see
   WHY something was classified as an evacuation, not just trust a bit).

2. BC DataBC (run_aurora_evacuations_bc)
   WFS GeoJSON, BC's own aggregated "Evacuation Orders and Alerts" layer
   (Emergency Management BC + every BC Local Government/First Nation, fed
   into the BC Geographic Warehouse hourly). ORDER_ALERT_STATUS ("Order" =
   mandatory evacuation vs "Alert" = be-ready warning) is kept as its own
   column deliberately — collapsing it into one undifferentiated status
   would erase the single most operationally important field this source
   provides. Licence: Open Government Licence – BC (attribution required).
"""
import datetime
import logging
import os
import re
import urllib.request
import urllib.error
import json
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from sqlalchemy import text

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "archie-aurora/1.0 (what-the-fact.com; weather ingest)"}
_TIMEOUT = int(os.environ.get("AURORA_EVAC_HTTP_TIMEOUT", "25"))
_CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
_ATOM_NS = "http://www.w3.org/2005/Atom"

_NAAD_INDEX_URLS = [
    "https://rss.naad-adna.pelmorex.com/",
    "https://rss1.naad-adna.pelmorex.com/",
]

# Event allowlist: only these CAP <event> values are even CANDIDATES for an
# evacuation. AMBER Alert, Silver Alert, thunderstorm/wind/fog warnings, Air
# Quality, etc. never reach the keyword check below, by construction — a
# false positive on a bare keyword scan of an unrelated event type is exactly
# the risk class the research flagged.
_EVAC_EVENT_ALLOWLIST = {
    "wildfire", "forest fire", "flood", "flash flood", "civil emergency",
    "civil danger", "dam failure", "dam break", "dyke break", "dike break",
    "hurricane",
}

# Word-boundary regex — NOT a bare substring check. "vacuuming" must never
# match; "residents must evacuate immediately" and "les résidents doivent
# évacuer" must always match. \w in Python's re with re.UNICODE (default for
# str patterns in Py3) matches accented letters, so évacu\w* correctly
# extends across é.
_EVAC_RE_EN = re.compile(r"\bevacuat\w*", re.IGNORECASE)
_EVAC_RE_FR = re.compile(r"\bévacu\w*", re.IGNORECASE | re.UNICODE)


def _classify_evacuation(event, description, instruction):
    """Return (is_evacuation, matched_keyword) — never raises, treats missing
    text as simply not matching rather than an error."""
    event_l = (event or "").strip().lower()
    if event_l not in _EVAC_EVENT_ALLOWLIST:
        return False, None
    combined = " ".join(t for t in (description, instruction) if t)
    if not combined:
        return False, None
    m = _EVAC_RE_EN.search(combined)
    if m:
        return True, m.group(0)
    m = _EVAC_RE_FR.search(combined)
    if m:
        return True, m.group(0)
    return False, None


# ---------------------------------------------------------------------------
# 1. NAAD / Alert Ready
# ---------------------------------------------------------------------------

def _fetch(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — fixed public host
        return r.status, r.read()


def _naad_entry_links(index_body):
    """Atom <entry><link rel="alternate" href="..."/> -> list of CAP XML
    URLs. Parsed with defusedxml — this is untrusted government XML over
    plain HTTP, same posture as ingest/weather/alerts.py."""
    try:
        root = ET.fromstring(index_body)
    except (ET.ParseError, DefusedXmlException) as exc:
        logger.debug("evac naad: index parse failed: %s", exc)
        return []
    links = []
    for entry in root.findall("{%s}entry" % _ATOM_NS):
        for link in entry.findall("{%s}link" % _ATOM_NS):
            if link.get("rel") == "alternate" and link.get("href"):
                links.append(link.get("href"))
    return links


def _tag(elem, name):
    child = elem.find("{%s}%s" % (_CAP_NS, name))
    return child.text if child is not None and child.text else None


def _parse_cap(raw, source_url):
    """One CAP-CP XML -> a row dict, or None. Never raises — a single
    malformed/non-evacuation file must not stop the run."""
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        logger.debug("evac naad: CAP parse failed for %s: %s", source_url, exc)
        return None

    identifier = _tag(root, "identifier")
    if not identifier:
        return None

    infos = root.findall("{%s}info" % _CAP_NS)
    info = None
    for i in infos:
        lang = (_tag(i, "language") or "").lower()
        if lang.startswith("en"):
            info = i
            break
    if info is None and infos:
        info = infos[0]  # fall back to whatever language exists rather than
        # dropping a real evacuation order just because it wasn't tagged en-*
    if info is None:
        return None

    event = _tag(info, "event")
    description = _tag(info, "description")
    instruction = _tag(info, "instruction")
    is_evac, matched = _classify_evacuation(event, description, instruction)
    if not is_evac:
        return None

    area = info.find("{%s}area" % _CAP_NS)
    area_desc = _tag(area, "areaDesc") if area is not None else None

    sender_name = None
    author = root.find("{%s}sender" % _CAP_NS)
    if author is not None and author.text:
        sender_name = author.text

    return {
        "identifier": identifier,
        "event": event,
        "status": _tag(root, "status"),
        "msg_type": _tag(root, "msgType"),
        "urgency": _tag(info, "urgency"),
        "severity": _tag(info, "severity"),
        "certainty": _tag(info, "certainty"),
        "headline": _tag(info, "headline"),
        "description": description,
        "instruction": instruction,
        "area_desc": area_desc,
        "matched_keyword": matched,
        "issuing_authority": sender_name,
        "sent_utc": _tag(root, "sent"),
        "effective_utc": _tag(info, "effective"),
        "expires_utc": _tag(info, "expires"),
        "source_url": source_url,
    }


def _run_naad(engine, dry_run):
    stats = {"entries": 0, "fetched": 0, "matched": 0, "upserted": 0, "parse_error": 0}
    index_body = None
    last_exc = None
    for url in _NAAD_INDEX_URLS:
        try:
            st, body = _fetch(url)
            if st == 200:
                index_body = body
                break
        except Exception as exc:  # noqa: BLE001 — try the mirror next
            last_exc = exc
            continue
    if index_body is None:
        return {"error": "NAAD index unreachable on both mirrors: %s" % last_exc}

    links = _naad_entry_links(index_body)
    stats["entries"] = len(links)
    rows = []
    for link in links:
        try:
            st, raw = _fetch(link)
        except (urllib.error.URLError, TimeoutError) as exc:
            stats["parse_error"] += 1
            logger.debug("evac naad: fetch failed for %s: %s", link, exc)
            continue
        if st != 200:
            stats["parse_error"] += 1
            continue
        stats["fetched"] += 1
        row = _parse_cap(raw, link)
        if row is None:
            continue
        stats["matched"] += 1
        rows.append(row)

    if dry_run:
        stats["upserted"] = len(rows)
        return stats

    with engine.begin() as c:
        for row in rows:
            result = c.execute(text("""
                INSERT INTO wtf.aurora_evacuations
                    (identifier, event, status, msg_type, urgency, severity,
                     certainty, headline, description, instruction, area_desc,
                     matched_keyword, issuing_authority, sent_utc,
                     effective_utc, expires_utc, source_url)
                VALUES (:identifier, :event, :status, :msg_type, :urgency, :severity,
                        :certainty, :headline, :description, :instruction, :area_desc,
                        :matched_keyword, :issuing_authority, :sent_utc,
                        :effective_utc, :expires_utc, :source_url)
                ON CONFLICT (identifier) DO UPDATE SET
                    status = EXCLUDED.status, msg_type = EXCLUDED.msg_type,
                    headline = EXCLUDED.headline, description = EXCLUDED.description,
                    instruction = EXCLUDED.instruction,
                    expires_utc = EXCLUDED.expires_utc, fetched_at = now()
            """), row)
            if result.rowcount > 0:
                stats["upserted"] += 1
    return stats


# ---------------------------------------------------------------------------
# 2. BC DataBC — Evacuation Orders and Alerts (WFS GeoJSON)
# ---------------------------------------------------------------------------

_BC_WFS_URL = (
    "https://openmaps.gov.bc.ca/geo/pub/"
    "WHSE_HUMAN_CULTURAL_ECONOMIC.EMRG_ORDER_AND_ALERT_AREAS_SP/ows"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeName=pub:WHSE_HUMAN_CULTURAL_ECONOMIC.EMRG_ORDER_AND_ALERT_AREAS_SP"
    "&outputFormat=json"
)


def _bc_feature_row(feature):
    """One GeoJSON feature -> a row dict, or None if it's missing the one
    field we key on (EVENT_NUMBER). Never raises on a shape surprise from a
    government feed — skip that feature, keep going."""
    props = feature.get("properties") or {}
    event_number = props.get("EVENT_NUMBER")
    if not event_number:
        return None
    return {
        "event_number": str(event_number),
        "event_name": props.get("EVENT_NAME"),
        "event_type": props.get("EVENT_TYPE"),
        "order_alert_name": props.get("ORDER_ALERT_NAME"),
        "order_alert_status": props.get("ORDER_ALERT_STATUS"),
        "issuing_agency": props.get("ISSUING_AGENCY"),
        "preoc_code": props.get("PREOC_CODE"),
        "population": props.get("MULTI_SOURCED_POPULATION"),
        "homes": props.get("MULTI_SOURCED_HOMES"),
        "date_modified": props.get("DATE_MODIFIED"),
        "event_start_date": props.get("EVENT_START_DATE"),
        "geometry": json.dumps(feature.get("geometry")) if feature.get("geometry") else None,
    }


def _run_bc(engine, dry_run):
    stats = {"features": 0, "upserted": 0}
    try:
        st, body = _fetch(_BC_WFS_URL)
    except Exception as exc:  # noqa: BLE001
        return {"error": "BC DataBC WFS unreachable: %s" % exc}
    if st != 200:
        return {"error": "BC DataBC WFS returned HTTP %s" % st}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return {"error": "BC DataBC WFS returned non-JSON: %s" % exc}

    features = payload.get("features") or []
    stats["features"] = len(features)
    rows = [r for r in (_bc_feature_row(f) for f in features) if r is not None]

    if dry_run:
        stats["upserted"] = len(rows)
        return stats

    with engine.begin() as c:
        for row in rows:
            result = c.execute(text("""
                INSERT INTO wtf.aurora_bc_evacuations
                    (event_number, event_name, event_type, order_alert_name,
                     order_alert_status, issuing_agency, preoc_code,
                     population, homes, date_modified, event_start_date, geometry)
                VALUES (:event_number, :event_name, :event_type, :order_alert_name,
                        :order_alert_status, :issuing_agency, :preoc_code,
                        :population, :homes, :date_modified, :event_start_date,
                        CAST(:geometry AS JSONB))
                ON CONFLICT (event_number) DO UPDATE SET
                    order_alert_status = EXCLUDED.order_alert_status,
                    date_modified = EXCLUDED.date_modified,
                    population = EXCLUDED.population, homes = EXCLUDED.homes,
                    geometry = EXCLUDED.geometry, fetched_at = now()
            """), row)
            if result.rowcount > 0:
                stats["upserted"] += 1
    return stats


# ---------------------------------------------------------------------------
# Heartbeats + entry points
# ---------------------------------------------------------------------------

def _heartbeat(engine, task, result, exc):
    """parliament.ingest_log on BOTH paths — same never-silent contract as
    every other ingest in this tree."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"),
                    {"t": task,
                     "f": int(result.get("fetched") or result.get("features") or 0),
                     "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001 — a heartbeat must never break the ingest
        logger.exception("evac: heartbeat write failed for %s", task)


def run_aurora_evacuations_naad(engine, dry_run=False):
    """Entry point. NEVER raises — returns a per-run summary dict."""
    task = "aurora_evacuations_naad"
    try:
        res = _run_naad(engine, dry_run)
        if not dry_run:
            _heartbeat(engine, task, res, None)
        return res
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s crashed", task)
        if not dry_run:
            _heartbeat(engine, task, {}, exc)
        return {"error": str(exc)}


def run_aurora_evacuations_bc(engine, dry_run=False):
    """Entry point. NEVER raises — returns a per-run summary dict."""
    task = "aurora_evacuations_bc"
    try:
        res = _run_bc(engine, dry_run)
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
    dr = "--dry-run" in sys.argv
    print("naad:", run_aurora_evacuations_naad(eng, dry_run=dr))
    print("bc:", run_aurora_evacuations_bc(eng, dry_run=dr))
