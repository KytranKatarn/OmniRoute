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
