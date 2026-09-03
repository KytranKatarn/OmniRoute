"""Parse Elections Canada "Official Voting Results" Table 12.

Pure, stdlib-only, no network and no database — same shape as
`ingest/weather/citypage_parse.py`, and for the same reason: a parser that
imports psycopg2 or requests makes its own guard tests SKIP silently on a box
that lacks them, which is how a parsing rule rots unnoticed (KB #290497).

SOURCE. open.canada.ca CKAN, org `elections`, dataset "<n>th General Election:
Official Voting Results", resource "Table 12: List of candidates by electoral
district and individual results". One row per candidate.

🔴 THE RULE THIS FILE EXISTS TO ENFORCE — measured over all 338 GE44 districts:

    rows carrying "**"                                     306   (NOT 338)
    districts with zero starred rows                        32
    districts with exactly one non-empty Majority          338 / 338
    ...and that row is also the top row by votes           338 / 338
    districts where the starred row is the top-vote row    285 / 338

`**` marks the INCUMBENT — a sitting MP who ran again — NOT the winner. Reading
it as "won" names the WRONG MP in 53 ridings. Verified GE44 seats won by
star-less first-time MPs: 10006 Joanne Thompson, 11004 Heath MacDonald,
12006 Lena Metlege Diab.

The winner is the row with a NON-EMPTY Majority. That is cross-checkable against
"highest votes", and the two agree 338/338 — so this module asserts BOTH and
reports a district where they disagree rather than quietly preferring one. A
disagreement means the file's shape changed, and silence there is how a bad
parse ships. KB mistake #301957.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

_INCUMBENT_MARK = "**"


@dataclass
class Candidate:
    district_number: str
    district_name: str
    province: str
    name: str
    party_raw: str
    party: str
    incumbent: bool          # the ** marker — NOT "won"
    votes: int
    vote_share: float | None
    majority: int | None     # non-empty ONLY on the winner
    elected: bool = False    # set by the district pass, never from **


@dataclass
class ParseReport:
    candidates: list[Candidate] = field(default_factory=list)
    districts: int = 0
    winners: int = 0
    incumbents: int = 0
    # Districts where "has a majority" and "most votes" disagree, or where the
    # winner count is not exactly one. Non-empty means the file changed shape.
    anomalies: list[str] = field(default_factory=list)
    # Cells whose party could not be resolved — typically a party fielding a
    # single candidate, where no boundary is derivable. Reported, NOT blocking:
    # one unparsed minor-party candidate must not withhold 338 real results.
    party_unresolved: list[str] = field(default_factory=list)


def _en(value: str) -> str:
    """Left (English) half of a bilingual 'English/Français' cell."""
    return (value or "").split("/")[0].strip()


def _num(value: str) -> str:
    """Cells arrive padded — '      5870' — and may carry thousands commas."""
    return re.sub(r"[\s,]", "", str(value or ""))


def _int(value: str) -> int | None:
    v = _num(value)
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float(value: str) -> float | None:
    v = _num(value)
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def derive_parties(cells: list[str]) -> list[str]:
    """Derive the party vocabulary from the candidate cells themselves.

    ⚠️ DO NOT USE TABLE 9 FOR THIS. Table 9 ("valid votes by political
    affiliation") looks like the authoritative list and is not the same
    vocabulary: it carries REGISTERED LEGAL names where Table 12 carries SHORT
    BALLOT names —

        Table 9 : "Liberal Party of Canada/Parti libéral du Canada"
        Table 12: "Liberal/Libéral"

    Measured: matching Table 12 cells against Table 9's list left 1,715 of 2,010
    unmatched. An earlier version of this module asserted the two were identical
    in a docstring and a commit message. They are not.

    HOW THIS WORKS. Every candidate cell ends with one bilingual party token and
    contains exactly ONE "/" (verified: 2,010 of 2,010 GE44 cells). Split there
    and the French half is unambiguous. Group the cells by that French half —
    every member of a group shares the same party, and differs only in the
    person's name — so the English party name is the LONGEST COMMON SUFFIX of
    the text before the slash. On GE44 this yields 24 parties and leaves ZERO
    cells unmatched, with sane counts (Liberal 338 = one per riding, Bloc 78 =
    Quebec's 78 seats).

    Self-derived means it needs no second fetch, cannot drift from the file it
    describes, and picks up a newly registered party automatically.
    """
    groups: dict[str, list[str]] = {}
    for cell in cells:
        raw = " ".join((cell or "").replace(_INCUMBENT_MARK, " ").split())
        if "/" not in raw:
            continue
        head, fr = raw.rsplit("/", 1)
        groups.setdefault(fr.strip(), []).append(head.strip())

    out = []
    for fr, heads in groups.items():
        # ⚠️ A GROUP OF ONE CANNOT YIELD A BOUNDARY. The longest common suffix
        # of a single string is that whole string, so a party with exactly one
        # candidate produced the vocabulary entry "Gus Stefanis Nationalist" —
        # the person's NAME became the party, the name column went empty, and
        # empty names then collided on the (election, district, name) key and
        # silently dropped a row. Measured: 1 singleton in GE44, 1 in GE43.
        # Two members is the minimum that can distinguish "the part they share"
        # (the party) from "the part they don't" (the person).
        if len(heads) < 2:
            continue
        shortest = min(heads, key=len)
        english = ""
        for i in range(len(shortest)):
            cand = shortest[i:]
            if all(h.endswith(cand) for h in heads):
                english = cand.strip()
                break
        if english:
            out.append(f"{english}/{fr}")
    return out


def split_candidate(cell: str, parties: list[str] | None = None) -> tuple[str, str, str, bool]:
    """'Ken McDonald ** Liberal/Libéral' -> (name, party_raw, party_en, incumbent).

    ⚠️ PASS THE VOCABULARY. The first version of this matched against nine
    hardcoded party names and, measured over the persisted GE43+GE44 rows,
    left 2,218 of 4,156 (53%) with NO party and leaked the party into the NAME
    on 2,374 (57%) — "René Villemure Bloc Québécois/". Multi-word real names
    like "NDP-New Democratic Party/NPD-Nouveau Parti démocratique" and
    "People's Party - PPC/Parti populaire - PPC" defeated both the match and the
    rsplit fallback.

    The fixture that "proved" the parser did not catch it: it was chosen for the
    winner-rule edge case and happened to contain only simple party names. It
    tested one property thoroughly and said nothing about this one.

    With `parties` supplied (normally derive_parties() over the same file) the
    split is an exact suffix match, LONGEST FIRST so a short party name cannot
    win inside a longer one. Without it, nothing is guessed — see below.
    """
    raw = (cell or "").strip()
    incumbent = _INCUMBENT_MARK in raw
    raw = raw.replace(_INCUMBENT_MARK, " ")
    raw = re.sub(r"\s{2,}", " ", raw).strip()

    if parties:
        for p in sorted(parties, key=len, reverse=True):
            if raw.endswith(p):
                name = raw[: -len(p)].strip()
                return name, p, _en(p), incumbent

    # No vocabulary, or nothing matched: return the cell as the NAME with no
    # party rather than guessing where the party begins.
    #
    # ⚠️ The previous fallback walked tokens from the START looking for the
    # first tail containing "/", which is the WHOLE STRING — so it returned an
    # empty name and put "Lainie Stewart People's Party - PPC" in the party
    # column. Empty names then collided on the (election, district, name)
    # unique key and 4,156 candidates collapsed to 1,213 rows. An unparsed name
    # is recoverable; a name in the party column that silently deletes rows is
    # not.
    return raw, "", "", incumbent


def parse_table12(text: str, parties: list[str] | None = None) -> ParseReport:
    """Parse Table 12 into candidates with `elected` resolved per district.

    The party vocabulary is DERIVED FROM THIS FILE by default (see
    derive_parties) — no second fetch, and it cannot drift from the data it
    describes. Pass `parties` only to override.
    """
    rep = ParseReport()
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        return rep

    # Headers are matched LOOSELY — the real file ships
    # "Percentage of Votes Obtained /Pourcentage…" with a stray space before the
    # slash, so an equality check on the header would fail on valid data.
    header = [h.lower() for h in rows[0]]

    def col(*needles: str, default: int | None = None) -> int | None:
        for i, h in enumerate(header):
            if all(n in h for n in needles):
                return i
        return default

    i_prov = col("province", default=0)
    i_dname = col("electoral district name", default=1)
    i_dnum = col("electoral district number", default=2)
    i_cand = col("candidate", default=3)
    i_votes = col("votes obtained", default=6)
    i_pct = col("percentage of votes", default=7)
    i_maj = col("majority", default=8)

    # Derive the party vocabulary from these very cells unless one was supplied.
    if parties is None:
        parties = derive_parties([r[i_cand] for r in rows[1:] if len(r) > i_cand])

    by_district: dict[str, list[Candidate]] = {}
    for r in rows[1:]:
        if len(r) <= i_maj:
            continue
        name, party_raw, party, incumbent = split_candidate(r[i_cand], parties)
        c = Candidate(
            district_number=(r[i_dnum] or "").strip(),
            district_name=_en(r[i_dname]),
            province=_en(r[i_prov]),
            name=name,
            party_raw=party_raw,
            party=party,
            incumbent=incumbent,
            votes=_int(r[i_votes]) or 0,
            vote_share=_float(r[i_pct]),
            majority=_int(r[i_maj]),
        )
        if not c.party:
            rep.party_unresolved.append(f"{c.district_number}: {r[i_cand].strip()[:60]}")
        by_district.setdefault(c.district_number, []).append(c)

    for dnum, cands in by_district.items():
        with_majority = [c for c in cands if c.majority is not None]
        top = max(cands, key=lambda c: c.votes)

        if len(with_majority) == 1:
            winner = with_majority[0]
            # Both signals must agree. They do 338/338 in GE44; a disagreement
            # means the file changed and is reported rather than resolved.
            if winner is not top:
                rep.anomalies.append(
                    f"district {dnum}: majority row '{winner.name}' is not the "
                    f"top-vote row '{top.name}'"
                )
            winner.elected = True
        else:
            rep.anomalies.append(
                f"district {dnum}: expected exactly 1 row with a majority, "
                f"found {len(with_majority)}"
            )

        rep.candidates.extend(cands)

    rep.districts = len(by_district)
    rep.winners = sum(1 for c in rep.candidates if c.elected)
    rep.incumbents = sum(1 for c in rep.candidates if c.incumbent)
    return rep
