"""city_identity.py — THE canonical city vocabulary for What The Fact (#6174).

The weather side and the news side of a "city page" had no shared key:

  WEATHER  wtf.aurora_city_site — 25 ECCC sites, e.g.
             s0000430  "Ottawa (Kanata - Orléans)"   s0000635  "Montréal"
  NEWS     wtf.articles.city — free text, e.g.
             "Ottawa"  "Montreal"  "Montréal"  "Toronto"

This module is the ONE place that reconciles them. The precedent is
`consumer/aurora_map._canon_prov`: a single map, extended in place, never
special-cased at a call site. The SA/SK bug (PR #2961) is what happens when a
vocabulary is handled in more than one spot — or in none.

⚠️ IT IS DELIBERATELY CONSERVATIVE. Every function returns None rather than
guessing. A city page showing the wrong city's news is worse than one showing
none, and the failure is silent.

────────────────────────────────────────────────────────────────────────────
THE FIVE TRAPS, all measured in live data 2026-09-01. Do not "simplify" past them.
────────────────────────────────────────────────────────────────────────────

1. 🔴 AMBIGUOUS NAMES. Two ECCC cities share a name with a far more famous
   foreign city:
       "Sydney"  -> Sydney NS (Canada)   vs Sydney, Australia
       "London"  -> London ON (Canada)   vs London, UK
   Live rows include `Sydney | NS | AU` and `Sydney | ON | GB` — the enricher
   itself is confused here. Name alone MUST NOT resolve these; they require a
   corroborating province. 13 "Sydney" and 8 "London" rows exist today.

2. 🔴 REGIONS ARE NOT CITIES. "Vancouver Island" is not Vancouver;
   "Cape Breton" is not Sydney. Substring or fuzzy matching would merge them.
   Only exact (folded) equality is used — never `in`, never difflib.

3. ACCENTS. "Montréal"/"Montreal" and "Québec"/"Quebec" both occur in
   articles.city. Folded before comparison.

4. ECCC PARENTHETICALS. "Ottawa (Kanata - Orléans)" is the site label for
   Ottawa. The suffix is stripped. NOTE this is also why `display_name` exists —
   and only 1 of 25 rows has one, so any UI MUST use
   coalesce(display_name, name_en) or it renders 24 blank cards.

5. JUNK IN THE CITY COLUMN. Live values include the literal string "null" (23
   rows), countries ("Nepal", "Israel"), and foreign cities. All resolve to None.

⚠️ SAINT JOHN vs ST. JOHN'S ARE DIFFERENT CITIES, one province apart:
   Saint John NB (s0000687) and St. John's NL (s0000280). Folding punctuation
   too aggressively merges them. Pinned by test.
"""
from __future__ import annotations

import re
import unicodedata

# canonical slug -> (ECCC site_code, province, display label)
# Extend HERE and nowhere else.
CANONICAL_CITIES: dict[str, tuple[str, str, str]] = {
    "calgary":       ("s0000047", "AB", "Calgary"),
    "edmonton":      ("s0000045", "AB", "Edmonton"),
    "kelowna":       ("s0000592", "BC", "Kelowna"),
    "vancouver":     ("s0000141", "BC", "Vancouver"),
    "victoria":      ("s0000775", "BC", "Victoria"),
    "winnipeg":      ("s0000193", "MB", "Winnipeg"),
    "fredericton":   ("s0000250", "NB", "Fredericton"),
    "moncton":       ("s0000654", "NB", "Moncton"),
    "saint-john":    ("s0000687", "NB", "Saint John"),
    "st-johns":      ("s0000280", "NL", "St. John's"),
    "halifax":       ("s0000318", "NS", "Halifax"),
    "sydney":        ("s0000670", "NS", "Sydney"),
    "yellowknife":   ("s0000366", "NT", "Yellowknife"),
    "iqaluit":       ("s0000394", "NU", "Iqaluit"),
    "hamilton":      ("s0000549", "ON", "Hamilton"),
    "london":        ("s0000326", "ON", "London"),
    "ottawa":        ("s0000430", "ON", "Ottawa"),
    "toronto":       ("s0000458", "ON", "Toronto"),
    "windsor":       ("s0000646", "ON", "Windsor"),
    "charlottetown": ("s0000583", "PE", "Charlottetown"),
    "montreal":      ("s0000635", "QC", "Montréal"),
    "quebec":        ("s0000620", "QC", "Québec"),
    "regina":        ("s0000788", "SK", "Regina"),
    "saskatoon":     ("s0000797", "SK", "Saskatoon"),
    "whitehorse":    ("s0000825", "YT", "Whitehorse"),
}

# 🔴 Trap 1. These slugs need a corroborating province before they may resolve.
# Both name a Canadian ECCC city AND a much larger foreign one.
AMBIGUOUS_WITHOUT_PROVINCE = {"sydney", "london"}

# 🔴 Trap 2 + 5. Seen in articles.city; each would otherwise be wrong or noise.
# Regions are NOT their nearest city, and a country is not a city.
#
# The second block (added #6174 second pass, 2026-09-06) is DIFFERENT in kind
# from the first: these are real, non-Canadian PLACES that landed in
# beat='municipal' through a beat-classifier bug (fixed separately, in the
# classify_beat prompt), not through any fault of this module. They are
# listed here — not solved by "just require CANONICAL_CITIES membership" —
# because #6174's second pass deliberately widened the news-side facet to
# accept any uncatalogued Canadian municipality (Kamloops, Kenora, Greater
# Sudbury, ... — real cities, just not among the 25 ECCC sites) rather than
# requiring membership in the 25-city list. That widening only works if the
# confirmed-foreign names are excluded explicitly; unlike canon_city()'s
# "return None rather than guess" default, is_known_junk() defaults to
# "assume real unless denylisted" for anything not already in
# CANONICAL_CITIES — a DELIBERATE, ACKNOWLEDGED trade-off (owner decision,
# 2026-09-06): a new foreign city not yet listed here can slip through as a
# facet until observed and added. Confirmed live in wtf.articles WHERE
# beat='municipal' AND city NOT resolvable via canon_city():
NOT_A_CITY = {
    "vancouver-island",   # region in BC, not the city Vancouver
    "cape-breton",        # island in NS, not Sydney
    "null", "none", "unknown", "n-a",
    "nepal", "israel", "canada",
    # confirmed foreign contamination in beat='municipal', 2026-09-06 —
    # none of these are municipal-government stories; see the classify_beat
    # prompt fix (platform_v2/tools/wtf_hub/routes.py) for the actual fix.
    "washington-d-c", "berlin", "amsterdam", "cleveland", "brownsville",
    "changzhi", "belgrade", "connecticut", "fujiyoshida", "cape-canaveral",
    "las-vegas", "los-angeles", "minneapolis", "moscow-region", "pleasanton",
    "san-francisco", "santa-clara", "tehran", "tel-aviv",
    # ambiguous with a far more common non-Canadian namesake, no corroborating
    # province available (unlike sydney/london, these aren't ECCC sites, so
    # AMBIGUOUS_WITHOUT_PROVINCE's province-corroboration path doesn't apply
    # to them) — same reasoning as Trap 1, applied conservatively.
    "paris", "cambridge",
}

_SITE_TO_SLUG = {code: slug for slug, (code, _p, _l) in CANONICAL_CITIES.items()}


def is_known_junk(name: str | None) -> bool:
    """True if `name` is confirmed non-Canadian or non-a-city (NOT_A_CITY).

    Distinct from canon_city(): this does NOT require membership in
    CANONICAL_CITIES, only that the folded name is NOT in the denylist. Used
    where a caller wants to accept uncatalogued-but-real Canadian cities
    (e.g. the /municipal facet, #6174) rather than restricting to the 25
    ECCC-linked ones — see the NOT_A_CITY comment above for the trade-off.
    """
    return _fold(name) in NOT_A_CITY


def _fold(name: str) -> str:
    """Lowercase, strip accents and the ECCC parenthetical, slugify.

    ⚠️ Punctuation becomes a separator, NOT nothing: 'St. John's' -> 'st-johns'
    stays distinct from 'Saint John' -> 'saint-john'. Deleting punctuation
    instead would push them toward each other.
    """
    if not name:
        return ""
    s = str(name).strip()
    s = re.sub(r"\s*\(.*?\)\s*$", "", s)                      # ECCC suffix
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))  # é -> e
    s = s.lower()
    # ⚠️ An apostrophe is INTRA-WORD, not a separator. Treating it as one turns
    # "St. John's" into "st-john-s" and the lookup misses. Delete it first; every
    # OTHER punctuation mark still separates, which is what keeps
    # "Saint John" (saint-john) distinct from "St. John's" (st-johns).
    s = s.replace("'", "").replace("’", "")              # ' and ’
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def canon_city(name: str | None, province: str | None = None) -> str | None:
    """Free-text city name -> canonical slug, or None when it cannot be resolved.

    Returns None — never a guess — for an unknown name, a region, a country, a
    foreign city, or an ambiguous name lacking a corroborating province.

        canon_city("Montréal")            -> "montreal"
        canon_city("Ottawa (Kanata)")     -> "ottawa"
        canon_city("Sydney")              -> None       # AU or NS?
        canon_city("Sydney", "NS")        -> "sydney"
        canon_city("Sydney", "ON")        -> None       # contradicts the site
        canon_city("Vancouver Island")    -> None       # a region
        canon_city("null")                -> None
    """
    slug = _fold(name)
    if not slug or slug in NOT_A_CITY or slug not in CANONICAL_CITIES:
        return None
    if slug in AMBIGUOUS_WITHOUT_PROVINCE:
        if not province:
            return None
        if province.strip().upper() != CANONICAL_CITIES[slug][1]:
            return None
    return slug


def slug_for_site_code(site_code: str | None) -> str | None:
    """ECCC site_code -> canonical slug. The weather side of the join."""
    return _SITE_TO_SLUG.get((site_code or "").strip())


def city_label(slug: str | None) -> str | None:
    """Canonical slug -> the human label (accented, ECCC suffix removed).

    ⚠️ This is the SHORT label. Do not render aurora_city_site.name_en directly —
    only 1 of 25 rows has a display_name, so name_en still carries
    "Ottawa (Kanata - Orléans)".
    """
    row = CANONICAL_CITIES.get(slug or "")
    return row[2] if row else None


def city_province(slug: str | None) -> str | None:
    row = CANONICAL_CITIES.get(slug or "")
    return row[1] if row else None
