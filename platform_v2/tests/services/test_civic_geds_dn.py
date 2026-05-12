import pytest
from services.civic_geds_dn import encode_dn, decode_dn, parse_dn, DnParseError

# Real samples observed during recon (geds-sage.gc.ca)
SAMPLES = [
    # (b64, decoded_dn, top_OU)
    ("T1U9Q01JUC1NQ0lRLE89R0MsQz1DQQ==", "OU=CMIP-MCIQ,O=GC,C=CA", "CMIP-MCIQ"),
    ("T1U9Q1NJUy1TQ1JTLE89R0MsQz1DQQ==", "OU=CSIS-SCRS,O=GC,C=CA", "CSIS-SCRS"),
    ("T1U9Q1NBLUFTQyxPPUdDLEM9Q0E=", "OU=CSA-ASC,O=GC,C=CA", "CSA-ASC"),
]


@pytest.mark.parametrize("b64,dn,_top", SAMPLES)
def test_decode_matches_known_sample(b64, dn, _top):
    assert decode_dn(b64) == dn


@pytest.mark.parametrize("b64,dn,_top", SAMPLES)
def test_encode_matches_known_sample(b64, dn, _top):
    assert encode_dn(dn) == b64


@pytest.mark.parametrize("_b64,dn,top", SAMPLES)
def test_parse_dn_extracts_top_OU(_b64, dn, top):
    parsed = parse_dn(dn)
    # Innermost OU = the dept's own acronym (last in the list)
    assert parsed["OU"][-1] == top
    assert parsed["O"] == "GC"
    assert parsed["C"] == "CA"


def test_parse_dn_with_nested_OU():
    dn = "OU=Branch X,OU=CSIS-SCRS,O=GC,C=CA"
    parsed = parse_dn(dn)
    # Order preserved as written; the dept (innermost in DN convention) is LAST in the OU list.
    assert parsed["OU"] == ["Branch X", "CSIS-SCRS"]


def test_round_trip():
    dn = "OU=Some Branch,OU=CSIS-SCRS,O=GC,C=CA"
    assert decode_dn(encode_dn(dn)) == dn


def test_decode_invalid_b64_raises():
    with pytest.raises(DnParseError):
        decode_dn("!!!not base64!!!")


def test_parse_dn_missing_O_raises():
    with pytest.raises(DnParseError):
        parse_dn("OU=Test")
