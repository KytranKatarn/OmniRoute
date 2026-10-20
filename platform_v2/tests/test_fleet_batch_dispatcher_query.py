"""fleet_batch_dispatcher: the node query must EXECUTE against the real schema, and the feature is default-off (#7371).

History: the query joined a relation `agent_welfare` that exists nowhere, so for months it failed every 5 minutes
(caught by a bare `except`, logged as a warning, returned []). A mocked cursor can never catch that. These tests run
the REAL SQL against the REAL DDL (tests/fixtures/fleet_batch_dispatcher_schema.sql, a pg_dump of the 7 tables + view)
in a throwaway PostgreSQL, over a TAGGED population (a row-count assertion guards against passing on empty tables).

Run with --noconftest: no application, production DB or login needed. The DB tests skip when docker or the local
pgvector/pgvector:pg16 image is unavailable (never pulls).
"""

import contextlib
import pathlib
import re
import shutil
import subprocess
import sys
import time
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import fleet_batch_dispatcher as fbd  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "fleet_batch_dispatcher_schema.sql"
IMAGE = "pgvector/pgvector:pg16"


# ── pure tests (no DB) ───────────────────────────────────────────────────────────────────────────────
def test_query_never_references_the_nonexistent_agent_welfare_relation():
    # `v_agent_welfare` / `agent_welfare_scores` are real; a bare `agent_welfare` is the bug.
    assert not re.search(r"(?<![\w])agent_welfare(?![\w])", fbd._NODE_QUERY)
    assert "v_agent_welfare" in fbd._NODE_QUERY and "agent_budgets" in fbd._NODE_QUERY


def test_feature_is_off_by_default_and_does_not_query_nodes(monkeypatch):
    monkeypatch.setattr(fbd, "_setting", lambda key: None)
    touched = []
    monkeypatch.setattr(
        fbd, "get_db_cursor", lambda *a, **k: touched.append(1) or (_ for _ in ()).throw(AssertionError)
    )
    assert fbd._query_available_nodes("analyze", 0.2) == []
    assert touched == []  # off means off: no SQL, no warning spam


@pytest.mark.parametrize("raw", ["", "false", "0", "off", "no", "garbage", None])
def test_only_explicit_truthy_values_enable_it(monkeypatch, raw):
    monkeypatch.setattr(fbd, "_setting", lambda key: raw)
    assert fbd.is_enabled() is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "on", "yes", " True "])
def test_truthy_values_enable_it(monkeypatch, raw):
    monkeypatch.setattr(fbd, "_setting", lambda key: raw if key == fbd._FLAG_ENABLED else None)
    assert fbd.is_enabled() is True


def test_a_settings_read_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(fbd, "get_db_cursor", boom)
    assert fbd._setting(fbd._FLAG_ENABLED) is None
    assert fbd.is_enabled() is False


# ── real-schema tests ────────────────────────────────────────────────────────────────────────────────
def _docker_ready():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def pg():
    if not _docker_ready():
        pytest.skip(f"docker or local image {IMAGE} unavailable")
    import psycopg2

    name = "fbd-test-" + uuid.uuid4().hex[:8]
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::5432",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=t",
            "--tmpfs",
            "/var/lib/postgresql/data:rw,size=256m",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        port = (
            subprocess.run(["docker", "port", name, "5432/tcp"], capture_output=True, text=True, check=True)
            .stdout.split(":")[-1]
            .strip()
        )
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
        cur.execute("\n".join(line for line in FIXTURE.read_text().splitlines() if not line.startswith("\\")))
        cur.execute("SET session_replication_role = replica")  # seed without FK/trigger ordering concerns
        yield conn
        conn.close()
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _seed(cur, table, **vals):
    schema, name = table.split(".")
    cur.execute(
        """select column_name, data_type from information_schema.columns
           where table_schema=%s and table_name=%s and is_nullable='NO' and column_default is null""",
        (schema, name),
    )
    fill = {
        "text": "x",
        "character varying": "x",
        "integer": 1,
        "bigint": 1,
        "boolean": True,
        "numeric": 1,
        "double precision": 1.0,
        "timestamp without time zone": "2026-01-01",
        "timestamp with time zone": "2026-01-01T00:00:00Z",
        "jsonb": "{}",
        "json": "{}",
        "ARRAY": "{}",
        "date": "2026-01-01",
    }
    row = dict(vals)
    for col, dt in cur.fetchall():
        row.setdefault(col, fill.get(dt, "x"))
    cols = ", ".join(f'"{c}"' for c in row)
    cur.execute(f"insert into {table} ({cols}) values ({', '.join(['%s'] * len(row))})", list(row.values()))


@pytest.fixture
def population(pg):
    """Nodes: ok, stale heartbeat, unapproved, resting agent, full queue, high stress. One agent each, all skill 'analyze'."""
    cur = pg.cursor()
    for t in (
        "node_agents",
        "remote_nodes",
        "agent_skills",
        "agent_budgets",
        "agent_emotional_state",
        "agent_rest_cycles",
        "agents",
    ):
        cur.execute(f"truncate public.{t} restart identity")
    cases = [
        # key,          agent, heartbeat,           approval,   shift,    stress, tasks, resting
        ("n_ok", 1001, "now()", "approved", "active", 0.2, 3, False),
        ("n_stale", 1002, "now() - interval '1 hour'", "approved", "active", 0.2, 3, False),
        ("n_unapproved", 1003, "now()", "pending", "active", 0.2, 3, False),
        ("n_resting", 1004, "now()", "approved", "active", 0.2, 3, True),
        ("n_full", 1005, "now()", "approved", "active", 0.2, 50, False),
        ("n_offshift", 1006, "now()", "approved", "barracked", 0.2, 3, False),
        (
            "n_stressed",
            1007,
            "now()",
            "approved",
            "active",
            0.9,
            3,
            False,
        ),  # max stress the DDL allows -> score 0.16 < 0.2
    ]
    for i, (key, agent, hb, appr, shift, stress, tasks, resting) in enumerate(cases, start=1):
        _seed(
            cur,
            "public.remote_nodes",
            id=i,
            node_id=key,
            node_name=f"Node {key}",
            approval_status=appr,
            status="online",
        )
        cur.execute("update public.remote_nodes set last_heartbeat = " + hb + " where id = %s", (i,))
        _seed(
            cur,
            "public.agents",
            id=agent,
            name=f"Agent {agent}",
            status="active",
            shift_state=shift,
            department="Executive Office",
            floor="BRIDGE",
        )
        _seed(cur, "public.node_agents", node_id=i, hub_agent_id=agent, name=f"na{agent}", status="active")
        _seed(cur, "public.agent_skills", agent_id=agent, skill_name="analyze", proficiency_level=3)
        _seed(cur, "public.agent_budgets", agent_id=agent, current_task_count=tasks, task_queue_limit=50)
        _seed(cur, "public.agent_emotional_state", agent_id=agent, stress_level=stress, energy_level=0.8)
        if resting:
            _seed(cur, "public.agent_rest_cycles", agent_id=agent)
            cur.execute("update public.agent_rest_cycles set ended_at = NULL where agent_id = %s", (agent,))
    cur.execute("select count(*) from public.remote_nodes")
    assert cur.fetchone()[0] == len(cases), "population not seeded: a test over empty tables proves nothing"
    return [c[0] for c in cases]


@pytest.fixture
def run(pg, monkeypatch):
    import psycopg2.extras

    @contextlib.contextmanager
    def cursor(*a, **k):
        c = psycopg2.connect(host=pg.info.host, port=pg.info.port, user="postgres", dbname="t")
        try:
            yield c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        finally:
            c.rollback()
            c.close()

    monkeypatch.setattr(fbd, "get_db_cursor", cursor)

    def go(enabled=True, allowed="", capability="analyze"):
        settings = {fbd._FLAG_ENABLED: "true" if enabled else "false", fbd._FLAG_ALLOWED_NODES: allowed}
        monkeypatch.setattr(fbd, "_setting", lambda key: settings.get(key))
        return fbd._query_available_nodes(capability, 0.2)

    return go


def test_query_runs_on_the_real_schema_and_selects_exactly_the_healthy_online_node(population, run):
    got = {n["node_id"] for n in run()}
    assert got == {"n_ok"}, f"expected only the healthy approved online on-shift node, got {sorted(got)}"


def test_each_exclusion_is_individually_effective(population, run):
    """Not vacuous: the excluded nodes DO exist and DO have the skill — they are filtered by the welfare/load rules."""
    got = {n["node_id"] for n in run()}
    for excluded in ("n_stale", "n_unapproved", "n_resting", "n_full", "n_offshift", "n_stressed"):
        assert excluded in population and excluded not in got


def test_score_reflects_welfare_and_load(population, run):
    (node,) = [n for n in run() if n["node_id"] == "n_ok"]
    # stress 0.2, energy 0.8, util 3/50: (1-.2)*.3 + .8*.2 - .06*.5 = 0.37
    assert node["score"] == pytest.approx(0.37, abs=0.001)


def test_unknown_capability_returns_nothing(population, run):
    assert run(capability="no_such_skill") == []


def test_allowed_nodes_restricts_the_result(population, run):
    assert {n["node_id"] for n in run(allowed="n_ok")} == {"n_ok"}
    assert run(allowed="n_stale") == []  # allowed but unhealthy stays excluded
    assert run(allowed="somebody_else") == []


def test_disabled_returns_nothing_even_with_a_healthy_node(population, run):
    assert run(enabled=False) == []
