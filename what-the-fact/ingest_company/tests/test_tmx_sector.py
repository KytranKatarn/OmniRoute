"""Pure-logic tests for the TMX->NAICS crosswalk + operating filter (no network).

Run:  cd what-the-fact && python3 -m ingest_company.tests.test_tmx_sector
(or via pytest). The live-fetch parse is exercised by the module's __main__ probe.
"""

from ingest_company.tmx_sector import (
    TMX_SECTOR_TO_NAICS,
    NON_OPERATING,
    is_operating,
    naics_for_tmx_sector,
)

# Must match the NAICS sectors present in shared.naics_codes (migration 037).
VALID_NAICS_SECTORS = {"21", "22", "31-33", "51", "52", "53", "54"}


def test_eleven_operating_sectors_map_above_threshold():
    assert len(TMX_SECTOR_TO_NAICS) == 11
    for tmx in TMX_SECTOR_TO_NAICS:
        r = naics_for_tmx_sector(tmx)
        assert r is not None, tmx
        assert r["naics_sector"] in VALID_NAICS_SECTORS, (tmx, r)
        assert r["naics_confidence"] >= 0.75, (tmx, r)   # ADR-EG-001 write threshold
        assert r["naics_label"], (tmx, r)
        assert is_operating(tmx), tmx


def test_non_operating_classes_filtered():
    for s in NON_OPERATING:
        assert naics_for_tmx_sector(s) is None, s
        assert not is_operating(s), s


def test_unknown_and_empty_return_none():
    for s in ("Banana Republic", "", None):
        assert naics_for_tmx_sector(s) is None, s
        assert not is_operating(s), s


if __name__ == "__main__":
    test_eleven_operating_sectors_map_above_threshold()
    test_non_operating_classes_filtered()
    test_unknown_and_empty_return_none()
    print("OK: tmx_sector unit tests passed")
