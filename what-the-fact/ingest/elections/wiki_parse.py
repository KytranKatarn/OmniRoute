"""PURE parser: a Wikipedia general-election article's wikitext -> one history row.

Stdlib only, no network, no DB (so its guard tests cannot silently SKIP — KB #290497).
Reads the `{{Infobox election}}` template: election_date, party1..N / seats1..N /
popular_vote1..N, turnout. Returns None — never a guess — when the shape is not what
we recognise, so a changed page is skipped and reported instead of persisted wrong.
"""
from __future__ import annotations

import datetime as dt
import re

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _template_block(text: str, name_re: str) -> str | None:
    m = re.search(r"\{\{\s*" + name_re, text, re.I)
    if not m:
        return None
    depth, i = 0, m.start()
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1; i += 2
        elif two == "}}":
            depth -= 1; i += 2
            if depth == 0:
                return text[m.start():i]
        else:
            i += 1
    return None


def _split_params(block: str) -> dict:
    inner = block[2:-2]
    params, cur, depth, i = [], "", 0, 0
    while i < len(inner):
        two = inner[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur += two; i += 2; continue
        if two in ("}}", "]]"):
            depth -= 1; cur += two; i += 2; continue
        if inner[i] == "|" and depth == 0:
            params.append(cur); cur = ""
        else:
            cur += inner[i]
        i += 1
    params.append(cur)
    out = {}
    for p in params[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def clean(v: str) -> str:
    v = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", v, flags=re.S)
    prev = None
    while prev != v:                       # strip nested {{templates}}
        prev, v = v, re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<[^>]+>", "", v)
    return re.sub(r"\s+", " ", v).strip()


def _int(v) -> int | None:
    m = re.match(r"\s*([\d,]+)", clean(v or ""))
    return int(m.group(1).replace(",", "")) if m and m.group(1).replace(",", "") else None


def _pct(v) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", clean(v or ""))
    return float(m.group(1)) if m else None


def _date(raw: str) -> dt.date | None:
    m = re.search(r"\{\{\s*(?:start date|start-date)\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", raw, re.I)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    s = clean(raw)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(2).lower() in _MONTHS:
        return dt.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def parse_election(wikitext: str, expect_year: int | None = None) -> dict | None:
    block = _template_block(wikitext, r"Infobox\s+(?:legislative\s+)?election")
    if not block:
        return None
    p = _split_params(block)
    d = _date(p.get("election_date", ""))
    if d is None or (expect_year and d.year != expect_year):
        return None
    results = []
    for n in range(1, 21):
        party = clean(p.get(f"party{n}", ""))
        seats = _int(p.get(f"seats{n}"))
        if not party or seats is None:
            continue
        row = {"party": party, "seats": seats}
        votes = _int(p.get(f"popular_vote{n}"))
        if votes:
            row["votes"] = votes
        results.append(row)
    if len(results) < 2:
        return None
    total = None
    m = re.search(r"/\s*([\d,]+)", clean(p.get("seats1", "")) + " " + clean(p.get("seats_for_election", "")))
    if m:
        total = int(m.group(1).replace(",", ""))
    if total is None:
        total = _int(p.get("seats_for_election"))
    if total is not None and sum(r["seats"] for r in results) > total:
        return None  # inconsistent: refuse rather than persist
    t = _pct(p.get("turnout"))
    if total is not None and total > sum(r["seats"] for r in results):
        # The infobox itemises only the top parties. The remainder is ARITHMETIC
        # (total - itemised), labelled as such, so the row sums to the real total.
        results.append({"party": "Other / not itemised", "seats": total - sum(r["seats"] for r in results),
                        "derived": True})
    return {"election_date": d, "results": results, "seats_total": total,
            "turnout_pct": t if t and 0 < t <= 100 else None}


def parse_mayoral(wikitext: str, expect_year: int | None = None) -> dict | None:
    """Mayoral/municipal infobox -> {election_date, results:[{candidate, votes, pct}], turnout_pct}.
    Candidates sorted by votes (winner first); None on any shape we do not recognise."""
    block = _template_block(wikitext, r"Infobox\s+(?:legislative\s+)?election")
    if not block:
        return None
    p = _split_params(block)
    d = _date(p.get("election_date", ""))
    if d is None or (expect_year and d.year != expect_year):
        return None
    rows = []
    for n in range(1, 21):
        name = clean(p.get(f"candidate{n}", "") or p.get(f"nominee{n}", ""))
        votes, pct = _int(p.get(f"popular_vote{n}")), _pct(p.get(f"percentage{n}"))
        if name and (votes or pct is not None):
            row = {"candidate": name}
            if votes:
                row["votes"] = votes
            if pct is not None:
                row["pct"] = pct
            rows.append(row)
    if len(rows) < 2 or sum(r.get("pct", 0) for r in rows) > 100.5:
        return None
    rows.sort(key=lambda r: (-(r.get("votes") or 0), -(r.get("pct") or 0), r["candidate"]))
    t = _pct(p.get("turnout"))
    return {"election_date": d, "results": rows, "seats_total": None,
            "turnout_pct": t if t and 0 < t <= 100 else None}
