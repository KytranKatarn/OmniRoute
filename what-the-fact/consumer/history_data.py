"""Versioned, read-only research catalogue. No database or network access."""

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

DATA_DIR = Path(__file__).parent / "data" / "history"
MAP_DIR = Path(__file__).parent / "static" / "history"


def safe_source_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def folded(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def load_catalog():
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    raw = (DATA_DIR / "events.json").read_bytes()
    if manifest.get("schema_version") != 1 or hashlib.sha256(raw).hexdigest() != manifest.get("events_sha256"):
        raise ValueError("History catalogue integrity failure")
    data = json.loads(raw)
    events = data["events"]
    sources = {source["id"]: source for source in data["sources"]}
    if len(events) != manifest["events_count"] or len(sources) != manifest["sources_count"]:
        raise ValueError("History catalogue count mismatch")
    if len({e["id"] for e in events}) != len(events):
        raise ValueError("Duplicate event identity")
    for event in events:
        if not re.fullmatch(r"CH-\d{4}", event["id"]) or event.get("publication_ready") is not False:
            raise ValueError("Unreviewed publication state")
        if not set(event["source_ids"]) <= sources.keys():
            raise ValueError("Missing source evidence")
        for key in ("start_year", "end_year"):
            if event.get(key) is not None and type(event[key]) is not int:
                raise ValueError("Invalid event date")
    maps = manifest["maps"]
    if len({m["year"] for m in maps}) != len(maps) or not maps:
        raise ValueError("Invalid map catalogue")
    for item in maps:
        if type(item["year"]) is not int or item["file"] != f"nrcan-{item['year']}.svg":
            raise ValueError("Invalid map identity")
        if hashlib.sha256((MAP_DIR / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Map integrity failure")
    for movement in data["movements"]:
        if movement.get("publication_ready") is not False or movement.get("route_geometry") is not None:
            raise ValueError("Movement is not a draft regional reference")
        if movement["event_id"] not in {e["id"] for e in events} or not set(movement["source_ids"]) <= sources.keys():
            raise ValueError("Missing movement evidence")
    return {
        "events": events,
        "sources": sources,
        "movements": data["movements"],
        "manifest": manifest,
        "maps": sorted(maps, key=lambda item: item["year"]),
    }


def matching_events(catalog, *, query="", region="", theme="", province="", year=None, undated=False):
    needle = folded(query)
    found = []
    for event in catalog["events"]:
        start, end = event.get("start_year"), event.get("end_year")
        if region and region not in event.get("regions", []):
            continue
        if theme and theme not in event.get("themes", []):
            continue
        if province and event.get("province_context") != province:
            continue
        if undated and start is not None:
            continue
        if year is not None and (start is None or not start <= year <= (end if end is not None else start)):
            continue
        text = " ".join(
            str(event.get(k) or "")
            for k in ("title_en", "title_fr", "summary_en", "summary_fr", "historical_place", "present_day_context")
        )
        if needle and needle not in folded(text):
            continue
        found.append(event)
    return sorted(found, key=lambda event: (event.get("start_year") is None, event.get("start_year") or 0, event["id"]))


def frame_for_year(catalog, year):
    if year is None:
        return None
    candidates = [item for item in catalog["maps"] if item["year"] <= year]
    return candidates[-1] if candidates else None
