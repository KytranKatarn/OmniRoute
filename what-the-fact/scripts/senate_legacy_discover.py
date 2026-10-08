#!/usr/bin/env python3
"""One-time discovery of the Senate's per-senator PDF filename codes for Sept 2010 - June 2016 (see ingest/parliament/senate_legacy.py).

The Senate's old 'Past Reports' index is gone, so the file list is rebuilt: Wikidata gives who held a Senate seat in the window
(dated position statements), and each candidate's file code ('<Surname5><GivenInitial>', e.g. AndreA for Andreychuk, A. Raynell) is
FOUND by probing the 26 possible initials in a period they sat. A hit counts ONLY when the PDF's own printed name carries the
candidate's surname — so a code that exists for someone else is never attributed to them.

Writes ingest/parliament/data/senate_legacy_codes.json: [{code, name, family, first_seen, first_end}]. Run from anywhere with
outbound HTTPS (it only READS); the loader then needs no Wikidata. Re-run to refresh; it never deletes a code already recorded.
"""
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.parliament import senate_legacy as sl                      # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "ingest" / "parliament" / "data" / "senate_legacy_codes.json"
SPARQL = """
SELECT ?p ?pLabel ?family ?start ?end WHERE {
  ?p p:P39 ?st . ?st ps:P39 wd:Q18524027 .
  OPTIONAL { ?st pq:P580 ?start . } OPTIONAL { ?st pq:P582 ?end . }
  FILTER( !BOUND(?start) || ?start <= "2016-07-01T00:00:00Z"^^xsd:dateTime )
  FILTER( !BOUND(?end) || ?end >= "2010-09-01T00:00:00Z"^^xsd:dateTime )
  OPTIONAL { ?p wdt:P734 ?f . ?f rdfs:label ?family . FILTER(LANG(?family)="en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def candidates() -> dict:
    u = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(SPARQL)
    req = urllib.request.Request(u, headers={"User-Agent": "WTFIngest/1.0 (https://what-the-fact.com)", "Accept": "application/sparql-results+json"})
    rows = json.loads(urllib.request.urlopen(req, timeout=120).read())["results"]["bindings"]
    people: dict = {}
    for r in rows:
        k = r["p"]["value"]
        d = people.setdefault(k, {"label": r["pLabel"]["value"], "family": r.get("family", {}).get("value"), "start": None, "end": None, "open": False})
        s, e = r.get("start", {}).get("value", "")[:10], r.get("end", {}).get("value", "")[:10]
        if s and (d["start"] is None or s < d["start"]):
            d["start"] = s
        if e and (d["end"] is None or e > d["end"]):
            d["end"] = e
        if not e:
            d["open"] = True
    return people


def stems(person: dict) -> list:
    """Surname stems the Senate might have used: first 5 letters, with and without the part before a hyphen / a particle."""
    fam = person["family"] or person["label"].split()[-1]
    out = []
    for f in {fam, person["label"].split()[-1]}:
        f = _ascii(f)
        parts = [f, f.split("-")[0], f.split()[-1] if " " in f else f]
        for part in parts:
            st = re.sub(r"[^A-Za-z]", "", part)[:5]
            if st and st not in out:
                out.append(st)
    return out


def periods_for(person: dict) -> list:
    """Period ends overlapping the person's (loose) window, MIDDLE first — a mid-term period is the likeliest to have a file."""
    lo, hi = person["start"] or "2000-01-01", ("2100-01-01" if person["open"] or not person["end"] else person["end"])
    ov = [p for p in sl.PERIODS if p[0] <= hi and p[1] >= lo]
    ov.sort(key=lambda p: abs(sl.PERIODS.index(p) - (sl.PERIODS.index(ov[len(ov) // 2]) if ov else 0)))
    return ov


def find_code(person: dict) -> dict | None:
    fam_u = _ascii(person["family"] or person["label"].split()[-1]).upper()
    for per in periods_for(person)[:3]:
        end = per[1]
        for st in stems(person):
            for ini in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                code = f"{st}{ini}"
                try:
                    data = sl._get(sl.url_for(end, code))
                except Exception:
                    continue
                if not data:
                    continue
                rec = sl.parse_pdf(data)
                if rec and rec["name"] and fam_u.replace("-", " ").split()[-1] in _ascii(rec["name"]).upper():
                    return {"code": code, "name": rec["name"], "family": fam_u, "first_seen": per[0], "first_end": end}
    return None


def main() -> None:
    have = {r["code"]: r for r in json.loads(OUT.read_text())} if OUT.exists() else {}
    people = candidates()
    print(len(people), "candidates", flush=True)
    todo = [p for p in people.values() if periods_for(p)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(find_code, todo))
    miss = []
    for p, r in zip(todo, results):
        if r:
            have.setdefault(r["code"], r)
        else:
            miss.append(p["label"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sorted(have.values(), key=lambda r: r["code"]), indent=1, ensure_ascii=False) + "\n")
    print("codes found:", len(have), "| not found:", len(miss), sorted(miss), flush=True)


if __name__ == "__main__":
    main()
