"""Navigation aids for /ridings: ridings-per-province counts and an A-Z jump index (design-handoff/wtf-ridings.html, reduced to what the data supports).

Pure and stdlib-only. Counts are over EVERY riding of the election shown, not the filtered view, so the chart stays a map of the whole house while the
table below narrows. The jump index is over the rows actually listed: a letter with no riding in the current filter is returned as absent (rendered
muted, never a dead link).
"""

import unicodedata

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def letter_of(name):
    """First letter of a riding name, accents folded ('Épinay' -> 'E'), or None when the name does not start with a letter."""
    for ch in (name or "").strip():
        base = unicodedata.normalize("NFKD", ch)[:1].upper()
        return base if base in LETTERS else None
    return None


def province_counts(ridings):
    """[(province, count)] largest first, ties alphabetical. A riding with no province is not counted (it would be a bar labelled nothing)."""
    counts = {}
    for r in ridings:
        p = r.get("province")
        if p:
            counts[p] = counts.get(p, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def build_index(listed):
    """For the rows listed (in display order): the A-Z strip [(letter, present)] and {district_number: letter} for the row that opens each letter's group."""
    first = {}
    for r in listed:
        lt = letter_of(r.get("district_name"))
        if lt and lt not in first:
            first[lt] = r.get("district_number")
    return [(lt, lt in first) for lt in LETTERS], {num: lt for lt, num in first.items()}
