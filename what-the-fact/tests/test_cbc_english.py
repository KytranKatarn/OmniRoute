from ingest.sources.cbc_english import fetch_articles

FIXTURE = "what-the-fact/tests/fixtures/cbc_sample.xml"


def test_fetch_returns_dicts_with_expected_keys(monkeypatch):
    def fake_get(url, **kw):
        class R:
            status_code = 200
            content = open(FIXTURE, "rb").read()

            def raise_for_status(self):
                return None
        return R()

    monkeypatch.setattr("requests.get", fake_get)
    articles = fetch_articles()
    assert len(articles) >= 1
    for a in articles:
        assert set(a.keys()) >= {"external_id", "title", "body", "url", "published_at"}
        assert a["external_id"]
        assert a["url"].startswith("http")
