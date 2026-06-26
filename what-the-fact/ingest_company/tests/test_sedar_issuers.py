"""Pure-logic tests for the SEDAR+ reporting-issuers parser (no network).

Run:  cd what-the-fact && python3 -m ingest_company.tests.test_sedar_issuers
"""

from ingest_company.sedar_issuers import (
    is_operating_issuer,
    operating_issuers,
    parse_sedar_export,
)

# Header wording matches a real SEDAR+ reporting-issuers export.
SAMPLE = (
    "Name,Number,Reporting jurisdictions (determined by regulator),"
    "Principal jurisdiction,Type,In default,Active cease trade order\n"
    'Acme Mining Corp,000012345,"AB, BC, ON",ON,Other issuer,No,No\n'
    'Fidelity Whatever Fund,000099999,"ON",ON,Investment fund,No,No\n'
    'Defaulted Co,000055555,"BC",BC,Other issuer,Yes,No\n'
    'ZZ No Number,,"ON",ON,Other issuer,No,No\n'
)


def test_parse_drops_rows_without_name_or_number():
    recs = parse_sedar_export(SAMPLE)
    assert len(recs) == 3  # the no-number row is dropped
    assert all(r["name"] and r["sedar_number"] for r in recs)


def test_number_is_key_and_jurisdictions_split():
    recs = parse_sedar_export(SAMPLE)
    acme = next(r for r in recs if r["name"] == "Acme Mining Corp")
    assert acme["sedar_number"] == "000012345"
    assert acme["reporting_jurisdictions"] == ["AB", "BC", "ON"]
    assert acme["principal_jurisdiction"] == "ON"
    assert acme["in_default"] is False


def test_operating_filter_drops_investment_funds():
    recs = parse_sedar_export(SAMPLE)
    ops = operating_issuers(recs)
    names = {r["name"] for r in ops}
    assert "Fidelity Whatever Fund" not in names      # fund filtered
    assert names == {"Acme Mining Corp", "Defaulted Co"}
    assert is_operating_issuer("Other issuer")
    assert not is_operating_issuer("Investment Fund")  # case-insensitive


def test_default_flag_parsed():
    recs = parse_sedar_export(SAMPLE)
    dc = next(r for r in recs if r["name"] == "Defaulted Co")
    assert dc["in_default"] is True
    assert dc["cease_trade"] is False


def test_bytes_input_and_empty():
    assert parse_sedar_export(SAMPLE.encode("utf-8")) == parse_sedar_export(SAMPLE)
    assert parse_sedar_export("") == []


if __name__ == "__main__":
    test_parse_drops_rows_without_name_or_number()
    test_number_is_key_and_jurisdictions_split()
    test_operating_filter_drops_investment_funds()
    test_default_flag_parsed()
    test_bytes_input_and_empty()
    print("OK: sedar_issuers unit tests passed")
