"""mp_profile() party-colour lookup — case-sensitivity fix.

`mp_profile()` (the /mp/<slug> route) computed `party_colour` via a raw,
case-sensitive dict lookup against `_PARTY_COLOURS` (all-lowercase keys:
"conservative", "liberal", "ndp", "bloc", "green", "independent", "people").
`parliament.mps.party` stores Title-Case values from the OpenParliament sync
("Liberal", "Conservative", "NDP", "Bloc", "Green", "People's Party") — every
lookup missed and silently fell back to grey (#6b7280) on every MP profile
page. The sibling `mps_listing()` route (the /mps roster) never had this bug:
it already calls `_party_colour(...)`, a case-insensitive fuzzy-match helper.

Fix: route `mp_profile()` through the SAME `_party_colour()` helper instead
of the raw dict, so both routes resolve party colour identically. Nothing
else changed — riding/province rendering was already correct and untouched,
no DB/ingest changes, and the raw `_PARTY_COLOURS` dict itself is left in
place (grep confirms `_party_colour()` is the only remaining function that
reads from it internally; no other call site was touched).

Non-vacuity, measured against the pre-fix file from git rather than asserted:
`_raw_lookup_offenders()` run against
`git show HEAD~1:what-the-fact/consumer/routes.py` (or HEAD if unmerged)
reports the offending pattern present inside `mp_profile()`, and reports
nothing against the fixed working tree.
"""

import re
import subprocess
from pathlib import Path

ROUTES_PATH = Path(__file__).resolve().parent.parent / "consumer" / "routes.py"


def _mp_profile_body(source: str) -> str:
    """Extract the mp_profile() function body via its def..next-def span."""
    m = re.search(r"^def mp_profile\(.*?\):\n(.*?)(?=^def \w|\Z)", source, re.S | re.M)
    assert m, "mp_profile() not found in routes.py — has it been renamed/moved?"
    return m.group(1)


def _raw_lookup_offenders(mp_profile_body: str):
    """Detect the pre-fix case-sensitive raw-dict-lookup pattern."""
    offenders = []
    if re.search(r"_PARTY_COLOURS\.get\(", mp_profile_body):
        offenders.append("mp_profile() reads _PARTY_COLOURS directly (case-sensitive miss)")
    if not re.search(r"_party_colour\(", mp_profile_body):
        offenders.append("mp_profile() never calls the case-insensitive _party_colour() helper")
    return offenders


def test_mp_profile_uses_case_insensitive_party_colour_helper():
    source = ROUTES_PATH.read_text()
    body = _mp_profile_body(source)
    offenders = _raw_lookup_offenders(body)
    assert not offenders, f"party-colour lookup regressed to the case-sensitive bug: {offenders}"


def test_mp_profile_and_mps_listing_share_the_same_resolver():
    """Both routes must resolve party colour through the same mechanism —
    that convergence is the actual fix, not merely 'not the old bug'."""
    source = ROUTES_PATH.read_text()
    listing_match = re.search(r"^def mps_listing\(.*?\):\n(.*?)(?=^def \w|\Z)", source, re.S | re.M)
    assert listing_match, "mps_listing() not found in routes.py — has it been renamed/moved?"
    listing_body = listing_match.group(1)
    mp_body = _mp_profile_body(source)
    assert "_party_colour(" in listing_body, "mps_listing() lost its case-insensitive resolver"
    assert "_party_colour(" in mp_body, "mp_profile() does not use the shared resolver"


def test_detector_is_not_vacuous_against_the_pre_fix_source():
    """Prove the detector actually catches the bug it targets, rather than
    trivially passing against any input. Look at the commit before this
    fix landed — the offending pattern must have been present there."""
    result = subprocess.run(
        ["git", "log", "--format=%H", "-n", "5", "--", str(ROUTES_PATH)],
        cwd=ROUTES_PATH.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    commits = [c for c in result.stdout.strip().splitlines() if c]
    assert commits, "no git history for routes.py — cannot prove non-vacuity"

    found_offender = False
    for sha in commits:
        show = subprocess.run(
            ["git", "show", f"{sha}:what-the-fact/consumer/routes.py"],
            cwd=ROUTES_PATH.parent.parent,
            capture_output=True,
            text=True,
        )
        if show.returncode != 0:
            continue
        old_source = show.stdout
        if "def mp_profile(" not in old_source:
            continue
        old_body = _mp_profile_body(old_source)
        if _raw_lookup_offenders(old_body):
            found_offender = True
            break

    assert found_offender, (
        "could not find the pre-fix case-sensitive lookup in recent history — "
        "the detector may be vacuous (passes against everything)"
    )
