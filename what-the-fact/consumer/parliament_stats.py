"""PURE stat-tile logic for /mps (design wtf-mps.html `pl-stats`). No DB, no Flask.

The design's tiles read "Government" and "Official Opposition". The data cannot establish
who governs (a coalition, a confidence loss, a pending swearing-in), so these tiles say
LARGEST / SECOND-LARGEST party — what the rows actually show — never an office.

Party tiles are computed from the members the page was given, so they are only correct for
the UNFILTERED House; with a party/province filter active they are omitted rather than
describing a subset under the label "largest party". Nothing is ever shown as 0 when it
simply was not measured.
"""
from __future__ import annotations

from collections import Counter


def chamber_tiles(mps, senators, total_seats, filtered):
    tiles = []
    n_house = int(total_seats or 0) or len(mps or [])
    if n_house:
        tiles.append({"label": "House members", "value": f"{n_house:,}",
                      "detail": "current seats filled"})
    if not filtered:
        counts = Counter((m.get("party") or "").strip() for m in (mps or []))
        counts.pop("", None)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for label, (name, n) in zip(("Largest party", "Second-largest party"), ranked[:2]):
            tiles.append({"label": label, "value": f"{n:,}", "detail": f"{name} · seats held"})
    sens = senators or []
    if sens:
        groups = {(s.get("caucus") or "").strip() for s in sens} - {""}
        tiles.append({"label": "Senators", "value": f"{len(sens):,}", "detail": "current members"})
        if groups:
            tiles.append({"label": "Senate groups", "value": str(len(groups)),
                          "detail": "caucuses and non-affiliated"})
    return tiles
