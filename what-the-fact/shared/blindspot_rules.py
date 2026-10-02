"""The Blindspot call rule — ONE definition, shared by the ingest (which stores
story_clusters.blindspot_side) and the /blindspot page (which counts how many clusters
land in each outcome). Ported from design-handoff/wtf-blindspot.js; if you retune a
number, update that file's comment too — they must describe the same rule.
"""
from __future__ import annotations

MIN_TOTAL = 4     # fewer articles than this, no pattern to call
MIN_SIDES = 4     # partisan (L+R) coverage needed before a side can be judged
MINOR_MAX = 0.25  # quiet side must be <= 25% of the two-sided coverage
MIN_DIFF = 3      # and at least this many articles behind in absolute terms


def classify(l: int, c: int, r: int) -> str:
    """'L' / 'R' (the QUIET side — a left blindspot means left outlets were quiet),
    'thin' (too few articles, or too few partisan ones, to judge), or 'balanced'."""
    l, c, r = int(l or 0), int(c or 0), int(r or 0)
    if l + c + r < MIN_TOTAL:
        return "thin"
    sides = l + r
    if sides < MIN_SIDES:
        return "thin"
    minor, diff = min(l, r), abs(l - r)
    if minor / sides <= MINOR_MAX and diff >= MIN_DIFF:
        return "R" if l > r else "L"
    return "balanced"


def breakdown(rows) -> dict:
    """rows: iterable of (l, c, r, n) — n clusters share those counts. Returns the
    five numbers the page shows. Every cluster examined lands in exactly one bucket."""
    out = {"examined": 0, "called": 0, "left": 0, "right": 0, "balanced": 0, "thin": 0}
    for l, c, r, n in rows:
        n = int(n)
        k = classify(l, c, r)
        out["examined"] += n
        if k == "L":
            out["left"] += n; out["called"] += n
        elif k == "R":
            out["right"] += n; out["called"] += n
        else:
            out[k] += n
    return out
