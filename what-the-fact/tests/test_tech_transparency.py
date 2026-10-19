import tech.routes as tech_routes
from tech.app import create_app


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeConnection:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM wtf.articles a" in sql:
            fields = (
                "ai_analyzed ai_analyzed_at analysis_tier band bias_computed_at "
                "bias_confidence bias_ensemble_band bias_ensemble_score "
                "bias_v2_computed_at bias_v2_confidence bias_v2_label bias_v2_model "
                "bias_v2_score country_code geo_scope heuristic_version owner_name "
                "owner_type province_code rationale score source_bias_lean tier1_at "
                "tier2_at trigger_phrases"
            ).split()
            article = {field: None for field in fields}
            article.update({
                "id": 42,
                "title": "Evidence-backed sample story",
                "url": "https://example.test/story",
                "source_name": "Example News",
                "published_at": None,
                "ingested_at": None,
                "cluster_id": None,
            })
            return FakeResult([article])
        if "FROM wtf.fact_checks" in sql:
            return FakeResult([
                {
                    "claim": "Internal claim",
                    "verdict": "verified",
                    "evidence": "Internal evidence",
                    "checker": "V.E.R.I.F.Y.",
                    "checked_at": None,
                },
                {
                    "claim": "Partner claim",
                    "verdict": "mixed",
                    "evidence": "https://example.test/fact-check",
                    "checker": "GoogleFCT:Example Publisher",
                    "checked_at": None,
                },
            ])
        if "FROM wtf.audit_trail" in sql:
            return FakeResult([])
        raise AssertionError(f"Unexpected query in transparency test: {sql}")


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return FakeConnection()

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_transparency_page_renders_internal_and_partner_fact_checks(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-only")
    monkeypatch.setenv("KYTRAN_CLIENT_ID", "wtf-tech")
    monkeypatch.setenv("KYTRAN_CLIENT_SECRET", "test-only")
    monkeypatch.setenv("KYTRAN_AUTH_URL", "https://identity.example.test")
    monkeypatch.setenv("KYTRAN_REDIRECT_URI", "https://wtf.example.test/callback")
    monkeypatch.setattr(tech_routes, "_db", lambda: FakeEngine())
    monkeypatch.setattr(
        tech_routes.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline in test")),
    )

    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().get("/transparency/42")

    assert response.status_code == 200
    assert b"Internal claim" in response.data
    assert b"Partner claim" in response.data
    assert b"External Fact-Checks" in response.data
    assert b"V.E.R.I.F.Y." in response.data
