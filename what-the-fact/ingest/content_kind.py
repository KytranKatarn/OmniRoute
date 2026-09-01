"""Distinguish wire/press-release copy from journalism.

WHY THIS EXISTS
---------------
A press release has no political lean to measure. Scoring one for partisan bias
does not produce a wrong answer — it produces a meaningless one, and then that
meaningless number is averaged into the outlet's public bias reading.

Measured on Financial Post, 30 days (2026-09-01):

    wire copy        647 articles (43%)   avg bias -0.023
    journalism       868 articles         avg bias -0.191
    published        ----                 avg bias -0.107

The site reported -0.107 for an outlet whose journalism measures -0.191. Nearly
half the sample carried no signal, so the published figure sat at the midpoint
of two unrelated populations — the difference between calling Financial Post
"center" and "center-left".

This is the same defect class as the no-signal heuristic rows fixed in #3012:
a population that asserts nothing being averaged into a measurement. That fix
handled "the detector found no trigger terms"; this one handles "there was
never anything political to detect".

DELIBERATELY CONSERVATIVE
-------------------------
Every marker below is a distributor's own boilerplate, not a topic guess. We
would rather leave a press release classified as journalism than misclassify
real reporting as wire and silently drop it from the bias average — a false
positive here DELETES a legitimate signal from a public statistic.

That asymmetry is why there is no "looks corporate" heuristic, no company-name
matching, and no dateline rule. `KIND_JOURNALISM` is the fail-safe default and
every unrecognised input returns it.
"""

from __future__ import annotations

import re

KIND_JOURNALISM = "journalism"
KIND_WIRE = "wire"

VALID_KINDS = frozenset({KIND_JOURNALISM, KIND_WIRE})

# Distributor boilerplate. Each string is text the WIRE SERVICE inserts, not
# language a journalist would choose — that is the whole basis for the call.
#
# ⚠️ Order and specificity matter. "/CNW/" carries the slashes because a bare
# "CNW" appears inside ordinary words; "GLOBE NEWSWIRE" is matched
# case-insensitively because outlets render it GlobeNewswire, Globe Newswire
# and GLOBE NEWSWIRE in the same corpus.
_WIRE_MARKERS = (
    "globe newswire",
    "globenewswire",
    "/cnw/",
    "cnw telbec",
    "canada newswire",
    "business wire",
    "businesswire",
    "pr newswire",
    "prnewswire",
    "accesswire",
    "newsfile corp",
    "partnership content",
    "this section is partnership content",
)

# Exchange tickers are literal text, so they need no model to extract.
# Present in ~1.5% of all articles but concentrated in exactly this population.
_TICKER_RE = re.compile(
    r"\b((?:TSXV|TSX|CSE|NEO|NASDAQ|NYSE|OTCQB|OTCQX)\s*:\s*[A-Z][A-Z.]{0,6})\b"
)


def classify(title: str | None, body: str | None) -> str:
    """Return KIND_WIRE or KIND_JOURNALISM. Never raises, never returns None.

    Absence of a body is NOT evidence of anything — an unfetched article is
    journalism until proven otherwise, so it keeps the default.
    """
    haystack = f"{title or ''}\n{body or ''}".lower()
    if not haystack.strip():
        return KIND_JOURNALISM
    for marker in _WIRE_MARKERS:
        if marker in haystack:
            return KIND_WIRE
    return KIND_JOURNALISM


def is_wire(title: str | None, body: str | None) -> bool:
    return classify(title, body) == KIND_WIRE


# A figure is only worth surfacing WITH the sentence that gives it meaning.
# "2,493" alone is noise; "tested 2,493 patients across 61 community pharmacies"
# is a fact the reader can check against the source.
# ⚠️ Do NOT split on the period in an abbreviation. A naive (?<=[.!?])\s+ cut
# "Sept. 01, 2026 (GLOBE NEWSWIRE) — AVRICORE HEALTH INC." into a fragment and
# surfaced the DATELINE as a key figure. Datelines, corporate suffixes and
# honorifics all end in a period mid-sentence.
_ABBREV = (r"(?<!\bJan)(?<!\bFeb)(?<!\bMar)(?<!\bApr)(?<!\bJun)(?<!\bJul)"
           r"(?<!\bAug)(?<!\bSept)(?<!\bSep)(?<!\bOct)(?<!\bNov)(?<!\bDec)"
           r"(?<!\bInc)(?<!\bLtd)(?<!\bCorp)(?<!\bCo)(?<!\bDr)(?<!\bMr)(?<!\bMrs)"
           r"(?<!\bMs)(?<!\bSt)(?<!\bNo)(?<!\bvs)(?<!\bU\.S)(?<!\bN\.B)(?<!\bB\.C)")
_SENTENCE_SPLIT = re.compile(_ABBREV + r"(?<=[.!?])\s+")

# Numbers that carry a unit, a percent, a currency, or a magnitude word. A bare
# integer is deliberately NOT enough — that is how you end up quoting years,
# street numbers and list indices as "key figures".
_FIGURE_RE = re.compile(
    r"(?:[$£€]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|trillion|bn|m|k))?"      # $2.4 million
    r"|\d[\d,]*(?:\.\d+)?\s?%"                                                        # 19%
    r"|\d[\d,]*(?:\.\d+)?\s?(?:million|billion|trillion|per\s?cent|percent)"          # 19 percent
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s+per\s?cent\b"         # "Nineteen percent"
    # 88 patients / 61 pharmacies — a number followed by a noun.
    # ⚠️ The leading lookahead rejects a 4-digit YEAR in this branch. Without it
    # "…her bestselling 2019 novel…" qualifies as a "key figure", which is how a
    # novel's publication year reached the panel. `_BARE_YEAR` below was written
    # for this and is anchored ^...$, so it only ever rejected a string that IS a
    # year — it never fired inside a sentence, and the guard sat unwired while the
    # docstring claimed the case was handled.
    # A 4-digit 19xx/20xx before a noun is far more often a date than a count, and
    # a real count of that size normally carries a separator ("2,019 people") or a
    # currency/percent/magnitude marker, all of which the branches above still
    # catch. Dropping the ambiguous case is the conservative choice: a missing key
    # figure is honest, a wrong one is not.
    r"|\b(?!(?:19|20)\d{2}\s)\d[\d,]*(?:\.\d+)?\s+(?=[a-z])(?!years?\b|months?\b)[a-z]{3,}"
    r")",
    re.I,
)

# A sentence that is nothing but a year is not a finding either.
_BARE_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Wire/CMS boilerplate that repeats inside scraped bodies. A sentence that is
# mostly furniture is not a finding no matter how many digits it contains.
_FIGURE_NOISE = re.compile(
    r"article content|advertisement|sign up|subscribe|newsletter|"
    r"all rights reserved|©|cookie|read more|photo by|getty images"
    # ⚠️ Scraped bodies contain the PAGE, not just the article. SaltWire's
    # sidebar bled a car review and a back-to-school listicle into a hockey
    # story's body, and "…Sea-to-Sky corridor 1 hour ago Lifestyle Made in
    # Canada: Five back to school wardrobe staples…" duly qualified as a
    # "key figure". These are relative-time stamps and section labels that
    # only ever appear in navigation furniture, never mid-sentence in prose.
    r"|\b\d+\s+(?:seconds?|minutes?|mins?|hours?|days?)\s+ago\b"
    r"|\b\d+\s+min(?:ute)?s?\s+read\b"
    r"|\btrending\b|\bmost read\b|\brelated stories\b|\bmore from\b"
    # ⚠️ FOUND ON LIVE OUTPUT, not imagined. A real extraction was:
    #   "MORE ON POLITICS MORE VIDEOS Doug Ford's symbolic Lake Ontario sign
    #    cost $25k: Premier's office Ontario city s…"
    # — a recommendation rail glued to the body by a pre-#3029 capture. It has a
    # currency figure and reads as a sentence, so every earlier rule passed it.
    # These labels are SHOUTED section headers that no journalist writes mid-prose.
    r"|\bmore on\b|\bmore videos\b|\bmore stories\b|\bread more\b|\bwatch:|\bsign up\b"
    r"|\bmost popular\b|\brecommended\b|\byou may also like\b|\bin the news\b",
    re.I,
)

# A run of three or more consecutive SHOUTED words is a section header, not prose.
# Catches rails whose specific label is not in the list above, without needing to
# enumerate every publisher's vocabulary.
_SHOUTED_RUN = re.compile(r"\b[A-Z][A-Z&'’]{2,}(?:\s+[A-Z][A-Z&'’]{2,}){2,}\b")


def extract_key_figures(body: str | None, limit: int = 5) -> list[str]:
    """Sentences from the body that contain a quantified figure — VERBATIM.

    ⚠️ QUOTES, NEVER SUMMARISES. Every string returned is a span copied out of
    the article, so the reader can check it against the original and we cannot
    invent a statistic. On a site whose product is fact-checking, a fabricated
    number is the worst defect available; the no-fabrication rule that governs
    the email drafts applies at least as hard to a public article page.

    Deliberately conservative about what counts as a figure:
      - a bare integer does NOT qualify (that yields years, addresses, list
        indices) unless it is 4+ digits with separators
      - percent / currency / magnitude words DO qualify
      - boilerplate sentences are dropped even when they contain digits

    Returns [] rather than guessing when the body is short or absent — the
    caller renders nothing at all in that case.
    """
    if not body or len(body) < 200:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(body):
        s = " ".join(raw.split())
        if len(s) < 40 or len(s) > 320:
            continue
        if _FIGURE_NOISE.search(s) or _SHOUTED_RUN.search(s):
            continue
        if not _FIGURE_RE.search(s):
            continue
        key = s.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_tickers(body: str | None, limit: int = 6) -> list[str]:
    """Exchange tickers in first-seen order, de-duplicated, whitespace-normalised.

    'TSXV: AVCR' and 'TSXV:AVCR' are the same listing and must not render twice.
    """
    if not body:
        return []
    seen: list[str] = []
    for raw in _TICKER_RE.findall(body):
        norm = re.sub(r"\s*:\s*", ": ", raw.strip())
        if norm not in seen:
            seen.append(norm)
        if len(seen) >= limit:
            break
    return seen
