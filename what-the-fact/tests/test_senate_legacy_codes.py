"""The Senate file-code list (data/senate_legacy_codes.json) and the discovery script that builds it.

Every code was FOUND by probing and accepted only when the PDF's own printed name carried the senator's family; this re-asserts that
invariant on the committed file, so a hand edit that breaks it fails here.
"""
import json
import re
from pathlib import Path

from ingest.parliament import senate_legacy as sl

ROOT = Path(__file__).resolve().parent.parent


def _ascii(s: str) -> str:
    return s.upper().replace("É", "E").replace("È", "E").replace("Ï", "I").replace("-", " ")


def test_the_code_file_is_well_formed_and_every_family_appears_in_the_printed_name():
    codes = sl.load_codes()
    assert len(codes) >= 120
    assert len({c["code"] for c in codes}) == len(codes)                              # one entry per file code
    for c in codes:
        assert set(c) >= {"code", "name", "family", "first_seen", "first_end"}
        assert c["code"].isalpha() and c["name"] and c["family"]
        assert _ascii(c["family"]).split()[-1] in _ascii(c["name"])
        assert c["first_end"] in {end for _s, end in sl.PERIODS}                       # discovered in a real Senate period


def test_codes_found_by_hand_from_the_senates_own_pages_are_present():
    got = {c["code"] for c in sl.load_codes()}
    assert {"AndreA", "DuffyM", "DoyleN"} <= got                                       # found by probing
    assert {"NancyR", "LovelS", "NgoT", "RaineN", "SmithL"} <= got                     # taken from the archived 2015 index page
    assert {"DiNinC", "DeBanP"} <= got                                                 # pre-2015 leavers found with spelling variants


def test_discovery_script_only_reads_and_checks_the_printed_name():
    src = (ROOT / "scripts" / "senate_legacy_discover.py").read_text(encoding="utf-8")
    assert "sl._get(" in src and "sl.parse_pdf(" in src                                # fetches + parses through the shared reader
    assert re.search(r"fam_u\.replace\(.*\)\.split\(\)\[-1\] in _ascii\(rec\[\"name\"\]\)", src)   # a hit must carry the family
    assert "have.setdefault(" in src                                                   # never overwrites a code already recorded
    assert "sqlalchemy" not in src and "create_engine" not in src                      # no database access at all
