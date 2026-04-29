"""Tests for geocoder.py heuristic fallback."""
from unittest.mock import patch


def test_heuristic_ontario():
    with patch("ingest.geocoder.analyze", return_value=None):
        from ingest.geocoder import extract_geo
        result = extract_geo(1, "Toronto mayor announces new policy", "")
        assert result["province_code"] == "ON"
        assert result["geo_scope"] == "provincial"


def test_heuristic_quebec():
    with patch("ingest.geocoder.analyze", return_value=None):
        from ingest.geocoder import extract_geo
        result = extract_geo(1, "Montreal news", "")
        assert result["province_code"] == "QC"


def test_no_province_returns_national():
    with patch("ingest.geocoder.analyze", return_value=None):
        from ingest.geocoder import extract_geo
        result = extract_geo(1, "Federal budget announced", "")
        assert result["province_code"] is None
        assert result["geo_scope"] == "national"


def test_agent_result_used_when_valid():
    agent_result = {
        "province_code": "BC",
        "city": "Vancouver",
        "lat": 49.28,
        "lng": -123.12,
        "geo_scope": "municipal",
        "geo_confidence": 0.9,
    }
    with patch("ingest.geocoder.analyze", return_value=agent_result):
        from ingest.geocoder import extract_geo
        result = extract_geo(1, "anything", "")
        assert result["province_code"] == "BC"
        assert result["city"] == "Vancouver"
