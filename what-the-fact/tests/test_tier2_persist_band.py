"""tier2_upgrade.persist_upgrade must survive an untrusted model `band` (live bug, found 2026-10-20 on Citadel).

The model's band string was written straight into wtf.bias_scores.band (varchar(16), CHECK in the five bands). Over 24h
Postgres logged 914 `bias_band_check` violations and 128 `value too long for type character varying(16)`; each one rolled
back the WHOLE upgrade (fact_checks rewrite and the analysis_tier stamp share the transaction), so the article stayed
tier2_pending and was retried forever (6,853 never completed).

These tests run the REAL persist_upgrade against the REAL DDL (tests/fixtures/tier2_persist_schema.sql, a pg_dump of
wtf.articles / bias_scores / fact_checks) in a throwaway PostgreSQL. The DB tests skip when docker or the local
pgvector/pgvector:pg16 image is unavailable (never pulls). Run with --noconftest.
"""

import pathlib
import shutil
import subprocess
import sys
import time
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.bias_parse import coerce_band, coerce_score  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "tier2_persist_schema.sql"
IMAGE = "pgvector/pgvector:pg16"


# ── pure ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,score,want",
    [
        ("left", -0.8, "left"),
        ("Center_Left", -0.3, "center-left"),  # case / separator tolerated
        ("centre-right", 0.5, "center-right"),  # British spelling
        ("far-right", 0.9, "right"),  # unrecognised -> derived from the score
        ("center-left-leaning", -0.3, "center-left"),  # 19 chars: would overflow varchar(16)
        ("mixed", 0.0, "center"),  # a real 0.0 is a MEASUREMENT, not absence
        (None, -0.7, "left"),
        ("unknown", None, None),  # no score -> never overwrite
        ("right", None, None),  # a band WITHOUT a score is not a measurement
        ("right", "x", None),  # unparseable score == absent
        ("garbage", "garbage", None),
    ],
)
def test_coerce_band(raw, score, want):
    got = coerce_band(raw, score)
    assert got == want
    assert got is None or (len(got) <= 16 and got in {"left", "center-left", "center", "center-right", "right"})


@pytest.mark.parametrize("raw,want", [(0, 0.0), ("0", 0.0), (0.4, 0.4), (5, 1.0), (-9, -1.0), (None, None), ("", None), ("x", None), (True, None)])
def test_coerce_score(raw, want):
    assert coerce_score(raw) == want


# ── real DDL ─────────────────────────────────────────────────────────────────────────────────────────
def _docker_ready():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def engine():
    if not _docker_ready():
        pytest.skip(f"docker or local image {IMAGE} unavailable")
    import psycopg2
    import sqlalchemy as sa

    name = "t2band-test-" + uuid.uuid4().hex[:8]
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::5432", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
         "-e", "POSTGRES_DB=t", "--tmpfs", "/var/lib/postgresql/data:rw,size=256m", IMAGE],
        check=True, capture_output=True)
    try:
        port = subprocess.run(["docker", "port", name, "5432/tcp"], capture_output=True, text=True, check=True
                              ).stdout.split(":")[-1].strip()
        conn = None
        for _ in range(60):
            try:
                conn = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", dbname="t")
                break
            except psycopg2.OperationalError:
                time.sleep(1)
        assert conn is not None, "scratch postgres did not start"
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("create schema wtf")
        cur.execute("\n".join(line for line in FIXTURE.read_text().splitlines() if not line.startswith("\\")))
        conn.close()
        eng = sa.create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/t")
        yield eng
        eng.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _seed_article(eng, aid):
    """One quick_v1 article with its HEURISTIC bias row (what the tier-2 upgrade overwrites)."""
    import sqlalchemy as sa

    fill = {"text": "x", "character varying": "x", "integer": 1, "bigint": 1, "boolean": False, "numeric": 1,
            "double precision": 1.0, "timestamp without time zone": "2026-01-01", "timestamp with time zone": "2026-01-01T00:00:00Z",
            "jsonb": "{}", "json": "{}", "ARRAY": "{}", "date": "2026-01-01"}
    with eng.begin() as c:
        c.execute(sa.text("set session_replication_role = replica"))
        for table, vals in (("articles", {"id": aid, "analysis_tier": "quick_v1"}),
                            ("bias_scores", {"article_id": aid, "band": "center", "score": 0.0, "heuristic_version": "v3"})):
            cols = c.execute(sa.text(
                "select column_name, data_type from information_schema.columns where table_schema='wtf' and table_name=:t "
                "and is_nullable='NO' and column_default is null"), {"t": table}).fetchall()
            row = dict(vals)
            for col, dt in cols:
                row.setdefault(col, fill.get(dt, "x"))
            cols_sql = ", ".join('"%s"' % k for k in row)
            vals_sql = ", ".join(":" + k for k in row)
            c.execute(sa.text("insert into wtf.%s (%s) values (%s)" % (table, cols_sql, vals_sql)), row)


def _payload(band, score, claims=2):
    return {"agent": "V.E.R.I.F.Y.", "result": {
        "bias_summary": {"band": band, "score": score, "rationale": "because", "trigger_phrases": ["a"], "confidence": 0.8},
        "key_claims": [{"text": f"claim {i}", "verdict": "verified", "reasoning": "r"} for i in range(claims)]}}


def _persist(eng, aid, payload):
    from ingest import tier2_upgrade

    with eng.begin() as conn:
        return tier2_upgrade.persist_upgrade(conn, "wtf", aid, payload)


def _state(eng, aid):
    import sqlalchemy as sa

    with eng.connect() as c:
        band, score = c.execute(sa.text("select band, score from wtf.bias_scores where article_id=:i"), {"i": aid}).one()
        claims = c.execute(sa.text("select count(*) from wtf.fact_checks where article_id=:i"), {"i": aid}).scalar()
        tier = c.execute(sa.text("select analysis_tier from wtf.articles where id=:i"), {"i": aid}).scalar()
    return band, (None if score is None else float(score)), claims, tier


@pytest.mark.parametrize(
    "aid,band,score,want_band",
    [
        (101, "far-right", 0.9, "right"),  # CHECK violation before the fix
        (102, "center-left-leaning", -0.3, "center-left"),  # varchar(16) overflow before the fix
        (103, "Centre-Right", 0.5, "center-right"),
        (104, "left", -0.8, "left"),
    ],
)
def test_untrusted_band_no_longer_aborts_the_upgrade(engine, aid, band, score, want_band):
    _seed_article(engine, aid)
    assert _state(engine, aid)[:3] == ("center", 0.0, 0), "population not seeded: a test over empty tables proves nothing"
    assert _persist(engine, aid, _payload(band, score)) == 2
    got_band, got_score, claims, tier = _state(engine, aid)
    assert (got_band, got_score, claims, tier) == (want_band, score, 2, "quick_v1+full")


def test_no_usable_score_leaves_the_heuristic_band_but_still_persists_the_claims(engine):
    _seed_article(engine, 201)
    _persist(engine, 201, _payload("extreme-right-wing", None))
    band, score, claims, tier = _state(engine, 201)
    assert band == "center" and score == 0.0  # the heuristic reading is untouched
    assert claims == 2 and tier == "quick_v1+full"  # ...but the upgrade is NOT lost


def test_a_zero_score_is_a_measurement_not_absence(engine):
    _seed_article(engine, 301)
    _persist(engine, 301, _payload("mixed", 0.0))
    assert _state(engine, 301)[:2] == ("center", 0.0)


def test_a_non_numeric_model_score_does_not_abort_the_upgrade(engine):
    """score is numeric: the raw string 'high' raised DataError and rolled back the whole upgrade too."""
    _seed_article(engine, 401)
    assert _persist(engine, 401, _payload("left", "high")) == 2
    band, score, claims, tier = _state(engine, 401)
    assert (band, score, claims, tier) == ("center", 0.0, 2, "quick_v1+full")  # unparseable score == absent: no overwrite
