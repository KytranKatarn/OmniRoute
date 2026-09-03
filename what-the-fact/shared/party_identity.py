"""The ONE canonicalisation boundary for federal party names.

Sibling of shared/city_identity.py, and it exists for the same reason: a
CONTINUING party appears under DIFFERENT strings in different sources, and
grouping by the raw string silently splits it in two.

⚠️ THE BUG THIS PREVENTS, MEASURED, NOT HYPOTHESISED. Elections Canada Table 12
records the BALLOT name, and a ballot name can change between elections:

    GE43 (2019)  "People's Party"        315 candidates    294,092 votes
    GE44 (2021)  "People's Party - PPC"  312 candidates    840,993 votes

Grouped by the raw string, /parties would have reported that the PPC did not
exist in 2019 and appeared from nowhere with 840,993 votes in 2021. The truth is
the opposite of interesting-but-wrong: they ran a near-identical full slate both
times and their vote very nearly TRIPLED. The split would have destroyed the one
genuinely notable fact about them.

DESIGN RULES, in order of importance:

1. MERGE ONLY ON EVIDENCE. Every entry below is a pair actually observed in the
   ingested data, where the two labels are the same registered party. Where a
   rename is plausible but unproven from the data alone — "Maverick Party" (GE44)
   as successor to Wexit, "Marijuana Party" (GE44) vs "Radical Marijuana" (GE43)
   — NO merge is made. Inventing a merge fabricates continuity, which is worse
   than showing two rows a reader can see are related.

2. FAIL OPEN TO THE RAW LABEL. An unmapped name passes through unchanged. A new
   party, or a rename in a future election, renders honestly as itself rather
   than vanishing into a wrong bucket or an "Other" pile.

3. THE HOUSE IS A DIFFERENT VOCABULARY AND IS NOT MAPPED HERE. parliament.mps
   uses short forms ("Bloc", "NDP") for the SITTING house — a different event
   from any election in parliament.elections, with a different seat count (343
   after the 2023 redistribution, vs 338 in GE44). Canonicalising the two into
   one namespace would invite joining them, which would compare a 2025 House to
   2021 results. Kept deliberately separate; see display_house_party().
"""

from __future__ import annotations

# (observed label) -> (canonical display name)
#
# Both keys of each pair are recorded, including the one that is already the
# canonical form, so the table reads as a statement about the party rather than
# a one-way patch and a reviewer can see both halves of every merge.
_ALIASES: dict[str, str] = {
    # Ballot name gained its initialism between 2019 and 2021.
    "People's Party": "People's Party",
    "People's Party - PPC": "People's Party",
    # GE43 abbreviated what GE44 spells out. 50 and 36 candidates respectively.
    "ML": "Marxist-Leninist",
    "Marxist-Leninist": "Marxist-Leninist",
}

# Parties deliberately NOT merged, with the reason, so a later reader does not
# "fix" the omission. Data only, never consulted at runtime — it documents a
# decision rather than driving one.
NOT_MERGED: dict[str, str] = {
    "Maverick Party": "GE44 only. Widely described as the successor to Wexit, "
                      "but Wexit does not appear in the ingested data under any "
                      "label, so the continuity cannot be shown from the source.",
    "Marijuana Party": "GE44 (9 candidates) and GE43's 'Radical Marijuana' (4) "
                       "are separately registered parties, not a rename.",
    "PC Party": "GE43 only, 3 candidates. Not the historical Progressive "
                "Conservative party, which merged into the Conservative Party "
                "in 2003 — a name collision, and merging on it would be wrong.",
}


def canonical_party(label: str | None) -> str:
    """Canonical display name for an Elections Canada ballot party label.

    Unmapped labels pass through unchanged; None/blank becomes "" so a caller
    can filter it without a separate null check.
    """
    if not label:
        return ""
    return _ALIASES.get(label.strip(), label.strip())


def merged_labels() -> dict[str, list[str]]:
    """{canonical: [every raw label that maps to it]}, for the page's own
    disclosure. A merge the reader cannot see is a merge they cannot check —
    /parties renders this so the two aliases are visible on the page itself."""
    out: dict[str, list[str]] = {}
    for raw, canon in _ALIASES.items():
        out.setdefault(canon, []).append(raw)
    return {k: sorted(v) for k, v in out.items() if len(v) > 1}


def display_house_party(label: str | None) -> str:
    """Tidy a parliament.mps party label for display ONLY.

    ⚠️ Deliberately NOT routed through canonical_party. The House vocabulary is
    a separate namespace (rule 3 above) and mapping it into the election one
    would make a join look reasonable. Nothing here changes the string's
    identity — it only strips whitespace.
    """
    return (label or "").strip()
