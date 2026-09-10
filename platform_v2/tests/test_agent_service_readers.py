"""#6653 Phase 4 — cockpit READ helpers in agent_service (single-reader).

Fake cursor: asserts the SQL shape AND the mapped rows, so an empty test DB
cannot make these pass vacuously. Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_agent_service_readers.py -q
"""

import contextlib

import pytest

from services import agent_service as svc


class _Cur:
    def __init__(self, results):
        self._results = list(results)  # one fetch result per execute, in order
        self.sql = []
        self.params = []
        self._last = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(tuple(params or ()))
        self._last = self._results.pop(0) if self._results else []

    def fetchall(self):
        return list(self._last or [])

    def fetchone(self):
        rows = self._last or []
        return rows[0] if rows else None


@pytest.fixture
def cursor(monkeypatch):
    holder = {}

    def make(results):
        cur = _Cur(results)
        holder["cur"] = cur

        @contextlib.contextmanager
        def fake_get_db_cursor(*a, **k):
            yield (None, cur)

        monkeypatch.setattr(svc, "get_db_cursor", fake_get_db_cursor)
        return cur

    return make


def test_list_roster_filters_and_counts(cursor):
    cur = cursor([[{"n": 2}], [{"id": 1, "name": "F.O.R.G.E."}, {"id": 2, "name": "P.R.O.B.E."}]])
    rows, total = svc.list_roster(q="f.o", department="Engineering & Technology", worker_type="ai", limit=10, offset=5)
    assert total == 2 and [r["id"] for r in rows] == [1, 2]
    count_sql, list_sql = cur.sql
    assert "SELECT count(*)" in count_sql and "FROM agents a" in list_sql
    assert "a.department = %s" in list_sql and "a.worker_type = %s" in list_sql
    assert "ILIKE %s" in list_sql and "<> 'decommissioned'" in list_sql
    assert cur.params[1][-2:] == (10, 5)  # LIMIT, OFFSET last
    assert "ORDER BY" in list_sql and "LIMIT %s OFFSET %s" in list_sql


def test_list_roster_can_include_decommissioned(cursor):
    cur = cursor([[{"n": 0}], []])
    svc.list_roster(include_decommissioned=True)
    assert "decommissioned" not in cur.sql[1]


def test_list_roster_dotted_name_search_matches_stripped_name(cursor):
    # Agent names are dotted acronyms (F.O.R.G.E.) — a plain ILIKE against the raw
    # query silently misses a user typing the acronym on screen (#5272-shaped trap).
    cur = cursor([[{"n": 1}], [{"id": 5, "name": "F.O.R.G.E."}]])
    svc.list_roster(q="F.O.R.G.E.")
    count_sql, list_sql = cur.sql
    assert "REPLACE(a.name, '.', '')" in count_sql
    assert "REPLACE(a.name, '.', '')" in list_sql
    # Both the raw dotted pattern AND the dot-stripped pattern must be bound —
    # a plain "forge" query has to match the stored "F.O.R.G.E." row too.
    assert "%F.O.R.G.E.%" in cur.params[1]
    assert "%FORGE%" in cur.params[1]


def test_roster_facets_groups_departments_and_states(cursor):
    cur = cursor([[{"k": "Engineering & Technology", "n": 4}], [{"k": "active", "n": 3}, {"k": "barracked", "n": 1}]])
    f = svc.roster_facets()
    assert f == {"departments": {"Engineering & Technology": 4}, "states": {"active": 3, "barracked": 1}}
    assert "GROUP BY a.department" in cur.sql[0] and "GROUP BY a.shift_state" in cur.sql[1]


def test_get_agent_skills_reads_agent_skills(cursor):
    cur = cursor(
        [[{"skill_name": "code", "skill_category": "engineering", "proficiency_level": 5, "can_escalate_to": None}]]
    )
    out = svc.get_agent_skills(12)
    assert out[0]["skill_name"] == "code" and "FROM agent_skills" in cur.sql[0] and cur.params[0] == (12,)


def test_get_agent_budget_none_when_no_row(cursor):
    cursor([[]])
    assert svc.get_agent_budget(12) is None


def test_get_agent_budget_maps_row(cursor):
    cur = cursor(
        [
            [
                {
                    "token_limit_per_day": 250000,
                    "tokens_used_today": 112000,
                    "task_queue_limit": 500,
                    "current_task_count": 3,
                    "token_reset_at": None,
                }
            ]
        ]
    )
    out = svc.get_agent_budget(12)
    assert out["token_limit_per_day"] == 250000 and "FROM agent_budgets" in cur.sql[0]


def test_get_agent_recent_work_limits(cursor):
    cur = cursor(
        [
            [
                {
                    "id": 9,
                    "capability": "code",
                    "model_used": "qwen2.5:7b",
                    "provider": "ollama",
                    "success": True,
                    "duration_ms": 1200,
                    "created_at": None,
                }
            ]
        ]
    )
    out = svc.get_agent_recent_work(12, limit=5)
    assert out[0]["capability"] == "code" and "FROM task_execution_log" in cur.sql[0] and cur.params[0] == (12, 5)
