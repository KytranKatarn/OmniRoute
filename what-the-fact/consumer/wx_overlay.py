"""Map overlay layers for /weather (WX-1, task 7250, ADR #1134): radar rain rate and HRDPS cloud cover, from MSC GeoMet.

No Flask, no DB, no network: the network is injected (`fetch_text`, `fetch_bytes`), so nothing here touches the internet and every rule is testable.

THE ALLOWLIST IS THE SECURITY BOUNDARY. The proxy route serves only the keys in OVERLAYS, with a fixed layer, style, bbox and size. No part of a
request URL comes from the visitor, so the proxy cannot be pointed at another host or another layer (no SSRF), and the upstream load is one fetch per
layer per cache window however many people look at the page.

HONESTY RULES, encoded in the data below rather than left to the template:
  * every overlay carries `kind`: "observed" (radar) or "forecast" (HRDPS cloud). They are labelled differently and never styled alike;
  * the image is requested for an EXPLICIT time read from the service's own GetCapabilities, and that time is returned with the image from the same cache
    entry, so a label can never describe a different frame than the one drawn;
  * `stale` is computed, never assumed: radar is stale when its valid time is old; the model layer when our copy is old;
  * the cloud model covers only part of the country; `domain_note` says so.
"""

import re
import threading
import time
from datetime import datetime, timezone

from defusedxml import ElementTree as ET  # the stdlib parser does not guard against entity expansion; this product already depends on defusedxml

BBOX = (-141.0, 41.0, -52.0, 84.0)  # lon/lat (CRS:84), wide enough for every province and territory; matches the map's fit
SIZE = (1400, 800)                   # ~0.06 degree per pixel: finer than the 6-10 km the model layers resolve
MAX_BYTES = 3_000_000                # refuse anything larger than this from upstream
GEOMET = "https://geo.weather.gc.ca/geomet"
ATTRIBUTION = "Contains information licensed under the Open Government Licence – Canada. Source: Environment and Climate Change Canada, MSC GeoMet."

OVERLAYS = {
    "radar": {
        "layer": "RADAR_1KM_RRAI", "style": "Radar-Rain", "kind": "observed",
        "title": "Radar rain rate", "units": "mm/h", "nearest": True,
        "cache_s": 300, "stale_after_s": 30 * 60, "stale_basis": "valid",
        "note": "Observed by weather radar. A blank area means no rain was detected, or that no radar covers it, not that the sky is clear.",
        "domain_note": None,
    },
    "cloud": {
        "layer": "HRDPS.CONTINENTAL_NT", "style": "CLOUD", "kind": "forecast",
        "title": "Cloud cover (model forecast)", "units": "%", "nearest": False,
        "cache_s": 900, "stale_after_s": 3 * 3600, "stale_basis": "fetched",
        "note": "A forecast from Environment Canada's HRDPS weather model, not an observation of the sky.",
        "domain_note": "The model covers most of southern and central Canada, not the whole map; areas outside its domain are left blank.",
    },
}

_NS = {"w": "http://www.opengis.net/wms"}
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")   # always used with fullmatch: `$` would accept a trailing newline


def known(key):
    return key in OVERLAYS


def capabilities_url(key):
    return f"{GEOMET}?service=WMS&version=1.3.0&request=GetCapabilities&layer={OVERLAYS[key]['layer']}"


def getmap_url(key, valid_time):
    """GetMap for the allowlisted layer at an explicit, validated time. Raises ValueError on anything that is not a plain timestamp ending in Z."""
    if not _ISO.fullmatch(valid_time or ""):
        raise ValueError("valid_time must be a plain ISO timestamp ending in Z")
    o = OVERLAYS[key]
    b = ",".join(repr(v) for v in BBOX)
    return (f"{GEOMET}?service=WMS&version=1.3.0&request=GetMap&layers={o['layer']}&styles={o['style']}&crs=CRS:84&bbox={b}"
            f"&width={SIZE[0]}&height={SIZE[1]}&format=image/png&transparent=true&time={valid_time}")


def legend_url(key):
    o = OVERLAYS[key]
    return (f"{GEOMET}?version=1.3.0&service=WMS&request=GetLegendGraphic&sld_version=1.1.0&layer={o['layer']}&format=image/png&STYLE={o['style']}")


def parse_times(xml_text, layer):
    """{'time': iso, 'reference_time': iso|None} from the layer's own <Dimension> defaults. Raises ValueError if the layer or its time is absent,
    so a changed or empty capabilities document fails loudly instead of producing an unlabelled frame."""
    root = ET.fromstring(xml_text)
    for lyr in root.iter("{%s}Layer" % _NS["w"]):
        name = lyr.find("w:Name", _NS)
        if name is None or (name.text or "").strip() != layer:
            continue
        dims = {d.get("name"): d.get("default") for d in lyr.findall("w:Dimension", _NS)}
        t = dims.get("time")
        if not t or not _ISO.fullmatch(t):
            raise ValueError(f"no usable time default for {layer}")
        ref = dims.get("reference_time")
        return {"time": t, "reference_time": ref if ref and _ISO.fullmatch(ref) else None}
    raise ValueError(f"layer {layer} not in capabilities")


def png_ok(blob):
    return isinstance(blob, (bytes, bytearray)) and blob[:8] == b"\x89PNG\r\n\x1a\n" and 0 < len(blob) <= MAX_BYTES


def build_entry(key, fetch_text, fetch_bytes, now):
    """One cache entry: the image AND the time it is for. Raises on any upstream problem; the caller keeps the previous entry (stale, labelled)."""
    o = OVERLAYS[key]
    t = parse_times(fetch_text(capabilities_url(key)), o["layer"])
    png = fetch_bytes(getmap_url(key, t["time"]))
    if not png_ok(png):
        raise ValueError("upstream did not return a usable PNG")
    return {"png": bytes(png), "valid_time": t["time"], "reference_time": t["reference_time"], "fetched_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def describe(key, entry, now):
    """The public metadata for a cached entry (no image bytes)."""
    o = OVERLAYS[key]
    basis = _parse(entry["valid_time"] if o["stale_basis"] == "valid" else entry["fetched_at"])
    age = max(0, int((now.astimezone(timezone.utc) - basis).total_seconds()))
    return {
        "key": key, "title": o["title"], "kind": o["kind"], "units": o["units"], "nearest": o["nearest"],
        "valid_time": entry["valid_time"], "reference_time": entry["reference_time"], "fetched_at": entry["fetched_at"],
        "age_s": age, "stale": age > o["stale_after_s"],
        "note": o["note"], "domain_note": o["domain_note"], "attribution": ATTRIBUTION,
        "bbox": list(BBOX), "size": list(SIZE),
    }


class OverlayCache:
    """Per-process cache of one entry per overlay key.

    * a fresh entry is served without any upstream call;
    * on expiry exactly ONE caller refreshes (the others wait briefly, then fall back to the old entry);
    * a failed refresh keeps the previous entry (which `describe` will label stale) and backs off for `retry_after_fail` seconds, so a service outage costs
      one failed request a minute per layer, not one per visitor;
    * with no entry at all and the service down, `get` returns None and the route answers 503.
    """

    def __init__(self, fetch_text, fetch_bytes, clock=time.time, retry_after_fail=60, lock_wait=15, log=None):
        self._ft, self._fb, self._clock = fetch_text, fetch_bytes, clock
        self._retry, self._lock_wait, self._log = retry_after_fail, lock_wait, log
        self._st = {k: {"entry": None, "ts": 0.0, "fail_ts": None, "lock": threading.Lock()} for k in OVERLAYS}

    def get(self, key):
        st, o = self._st[key], OVERLAYS[key]
        now = self._clock()
        if st["entry"] and now - st["ts"] < o["cache_s"]:
            return st["entry"]
        if st["fail_ts"] is not None and now - st["fail_ts"] < self._retry:
            return st["entry"]
        if not st["lock"].acquire(timeout=self._lock_wait):
            return st["entry"]
        try:
            now = self._clock()
            if st["entry"] and now - st["ts"] < o["cache_s"]:      # someone else refreshed while we waited
                return st["entry"]
            try:
                st["entry"] = build_entry(key, self._ft, self._fb, datetime.fromtimestamp(now, tz=timezone.utc))
                st["ts"], st["fail_ts"] = now, None
            except Exception as exc:  # noqa: BLE001 - upstream trouble must never become a 500 on the page
                st["fail_ts"] = now
                if self._log:
                    self._log("wx overlay %s refresh failed: %s", key, exc)
            return st["entry"]
        finally:
            st["lock"].release()
