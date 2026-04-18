from datetime import datetime
from ingest.normalizer import canonicalize


def test_strips_html_from_body():
    raw = {"title": "T", "body": "<p>hello <b>world</b></p>", "url": "http://x",
           "external_id": "g-1", "published_at": datetime(2026, 4, 18)}
    out = canonicalize(raw)
    assert out["body"] == "hello world"


def test_truncates_title_to_1024():
    long = "x" * 2000
    raw = {"title": long, "body": "b", "url": "http://x",
           "external_id": "g-1", "published_at": datetime(2026, 4, 18)}
    out = canonicalize(raw)
    assert len(out["title"]) == 1024


def test_requires_external_id():
    import pytest
    raw = {"title": "T", "body": "b", "url": "http://x",
           "external_id": "", "published_at": datetime(2026, 4, 18)}
    with pytest.raises(ValueError, match="external_id"):
        canonicalize(raw)
