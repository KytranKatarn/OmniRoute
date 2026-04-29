import os
from flask import Blueprint, render_template, abort
from sqlalchemy import create_engine, text

bp = Blueprint("wtf", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


TEAM_AGENTS = [
    {
        "name": "F.A.C.T.",
        "full": "Factual Analysis, Credibility & Transparency",
        "role": "Director & Orchestrator",
        "model": "gemma3:12b",
        "description": "F.A.C.T. leads every ingest cycle — selecting the stories most worth investigating deeply, coordinating the team, and ensuring coverage is fair and complete.",
        "coming_soon": False,
    },
    {
        "name": "B.I.A.S.",
        "full": "Balanced Information Analysis & Scoring",
        "role": "Bias Analyst",
        "model": "gemma2:9b",
        "description": "B.I.A.S. reads every priority article and scores it on the political spectrum, surfacing the trigger phrases and framing choices that reveal editorial perspective.",
        "coming_soon": False,
    },
    {
        "name": "V.E.R.I.F.Y.",
        "full": "Verification, Evidence Review & Integrity",
        "role": "Fact-Checker",
        "model": "gemma2:9b",
        "description": "V.E.R.I.F.Y. extracts verifiable claims from each article and assigns a verdict — verified, mixed, disputed, or unverifiable — with reasoning.",
        "coming_soon": False,
    },
    {
        "name": "L.O.C.A.L.",
        "full": "Local Observer, Coverage & Area Liaison",
        "role": "Geographic Intelligence Analyst",
        "model": "llama3.2:3b",
        "description": "L.O.C.A.L. maps every story to a Canadian province, tracks coverage gaps across regions, and identifies news deserts where communities go unheard.",
        "coming_soon": False,
    },
    {
        "name": "I.N.K.",
        "full": "Investigative News & Knowledge",
        "role": "News Investigator",
        "model": "dolphin3",
        "description": "I.N.K. will detect investigative story threads across article clusters — finding the through-line when the same story unfolds across days and outlets.",
        "coming_soon": True,
    },
    {
        "name": "D.R.A.F.T.",
        "full": "Data Reduction & Factual Translation",
        "role": "Staff Writer",
        "model": "dolphin3",
        "description": "D.R.A.F.T. will generate WTF editorial summaries — translating dense news cycles into plain-language explainers.",
        "coming_soon": True,
    },
    {
        "name": "P.U.B.L.I.S.H.",
        "full": "Publish & Unified Broadcasting",
        "role": "Broadcast Editor",
        "model": "mistral:7b",
        "description": "P.U.B.L.I.S.H. will push top stories to social media and newsletter subscribers, bringing AI journalism to where Canadians actually consume news.",
        "coming_soon": True,
    },
]


@bp.get("/team")
def team():
    return render_template("team.html", agents=TEAM_AGENTS)


@bp.get("/")
def index():
    S = _schema()
    wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band,
                   a.ai_analyzed,
                   a.province_code
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            ORDER BY a.published_at DESC LIMIT 50
        """)).mappings().all()
    return render_template("index.html", articles=rows, wtf_tech_url=wtf_tech_url)


@bp.get("/article/<int:article_id>")
def article(article_id: int):
    import json as _json
    S = _schema()
    wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at,
                   a.ai_analyzed, a.province_code, a.cluster_id,
                   s.name AS source_name,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.trigger_phrases,
                   fc.overall_verdict, fc.claims AS fact_check_claims
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.fact_checks fc ON fc.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        abort(404)
    # Normalise JSONB fields — driver may return str or list
    a = dict(row)
    for field in ("trigger_phrases", "fact_check_claims"):
        val = a.get(field)
        if isinstance(val, str):
            try:
                a[field] = _json.loads(val)
            except Exception:
                a[field] = []
        elif val is None:
            a[field] = []
    return render_template("article.html", a=a, wtf_tech_url=wtf_tech_url)
