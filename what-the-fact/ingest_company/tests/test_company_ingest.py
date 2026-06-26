"""Pure-logic tests for the company-layer join + entity builder (no network).

Run:  cd what-the-fact && python3 -m ingest_company.tests.test_company_ingest
"""

from ingest_company.company_ingest import (
    _norm_name,
    build_company_entities,
    ingest_payload,
)

TMX = [
    {"name": "Acme Mining Corp", "ticker": "ACM", "exchange": "TSX",
     "tmx_sector": "Mining", "tmx_sub_sector": "", "naics_sector": "21",
     "naics_label": "Mining, quarrying, and oil and gas extraction", "naics_confidence": 0.90},
    {"name": "Beta Tech Inc", "ticker": "BTA", "exchange": "TSXV",
     "tmx_sector": "Technology", "tmx_sub_sector": "Software", "naics_sector": "51",
     "naics_label": "Information and cultural industries", "naics_confidence": 0.85},
]


def test_norm_name_strips_suffixes_and_bilingual():
    assert _norm_name("Acme Mining Corporation") == _norm_name("Acme Mining Corp") == "acme mining"
    assert _norm_name("Foo Inc. / Foo Inc.") == "foo"
    assert _norm_name("The Widget Company Ltd") == "widget"


def test_build_entities_with_sedar_match_and_miss():
    sedar = [{"name": "ACME MINING CORPORATION", "sedar_number": "000012345", "type": "Other issuer"}]
    ents = build_company_entities(TMX, sedar)
    assert len(ents) == 2
    assert all(e["entity_type"] == "organization" and isinstance(e["role"], dict) for e in ents)

    acme = next(e for e in ents if e["canonical_name"] == "Acme Mining Corp")
    assert acme["metadata"]["naics_sector"] == "21"
    assert acme["metadata"]["naics_source"] == "tmx_derived"
    assert acme["metadata"]["naics_confidence"] == 0.90
    assert acme["metadata"]["ticker"] == "ACM"
    assert acme["external_ids"] == [{"key_type": "sedar_issuer", "key_value": "000012345"}]

    beta = next(e for e in ents if e["canonical_name"] == "Beta Tech Inc")
    assert beta["external_ids"] == []          # no SEDAR match -> no key
    assert beta["metadata"]["tmx_sub_sector"] == "Software"


def test_no_sedar_means_no_external_ids():
    ents = build_company_entities(TMX, None)
    assert all(e["external_ids"] == [] for e in ents)
    assert all(e["metadata"]["naics_source"] == "tmx_derived" for e in ents)


def test_market_cap_not_ingested():
    # ToU: quotes are not republished — metadata must carry no market_cap.
    ents = build_company_entities([{**TMX[0], "market_cap": "1,234,567"}], None)
    assert "market_cap" not in ents[0]["metadata"]


def test_ingest_payload_shape():
    p = ingest_payload(build_company_entities(TMX, None))
    assert p["product"] == "market-watch"
    assert p["mentions"] == [] and p["relationships"] == []
    assert len(p["entities"]) == 2


if __name__ == "__main__":
    test_norm_name_strips_suffixes_and_bilingual()
    test_build_entities_with_sedar_match_and_miss()
    test_no_sedar_means_no_external_ids()
    test_market_cap_not_ingested()
    test_ingest_payload_shape()
    print("OK: company_ingest unit tests passed")
