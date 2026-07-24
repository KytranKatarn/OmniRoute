"""No live SQL may reference the DROPPED `station_assignments` table (#5157).

`station_assignments` was dropped when agents moved to belonging to departments
(`agents.department`). Several call sites were migrated — `mcp_server/tools/admin.py`
even carries comments saying "station_assignments table dropped — agents belong to
departments via agents.department" — but four SQL statements were missed and kept
joining the ghost table. `to_regclass('public.station_assignments')` is NULL, so
every one of them raised ``UndefinedTable`` at runtime:

* ``mcp list_agents`` — broken outright on every call.
* ``mcp get_station_assignments`` — both branches broken.
* ``app.api_module_agents`` — worse: the exception was swallowed by a bare
  ``except`` into ``{"agent_name": None}``, so /api/module-agents silently reported
  "no agent" for EVERY module instead of its director. Failing loudly would have
  been caught in a day; failing silently lasted until someone went looking.

The surviving link is ``bridge_stations.station_name = agents.department``, verified
against live data: 16/16 active stations match a department, each with exactly one
``is_department_ai`` (its primary). The one gap is News & Media, which has no
bridge_stations row — it was added after the stations were seeded (tracked
separately; a missing station must degrade to "no crew", never to an exception).

These tests are deliberately grep-based as well as behavioural: the point is that a
*new* reference to the dead table must never reappear, and only source inspection
can prove absence across files.
"""

from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Files whose live SQL referenced the dropped table before this fix.
_MIGRATED_FILES = (
    "app.py",
    os.path.join("mcp_server", "tools", "admin.py"),
)

# `node_station_assignments` is a DIFFERENT table that DOES exist (fleet node ->
# department mapping). Matching it here would be a false positive, so the pattern
# requires a non-word char (or line start) before the name.
_DEAD_TABLE_SQL = re.compile(r"(?<![\w_])station_assignments\b")


def _sql_referencing_dead_table(path: str) -> list[str]:
    """Lines that reference the dropped table in SQL (comments excluded)."""
    hits = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not _DEAD_TABLE_SQL.search(line):
                continue
            stripped = line.strip()
            # Prose/SQL comments explaining the migration are fine and wanted.
            if stripped.startswith("#") or stripped.startswith("--"):
                continue
            if "node_station_assignments" in line:
                continue
            hits.append(f"{n}: {stripped}")
    return hits


@pytest.mark.parametrize("relpath", _MIGRATED_FILES)
def test_no_live_sql_references_the_dropped_table(relpath):
    """A JOIN on a non-existent relation is a guaranteed runtime error."""
    path = os.path.join(_ROOT, relpath)
    hits = _sql_referencing_dead_table(path)
    assert hits == [], f"{relpath} still references the dropped station_assignments table:\n" + "\n".join(hits)


def test_dropped_table_is_actually_absent(db_conn):
    """Pin the premise. If the table is ever recreated, this whole fix is moot
    and these tests should be revisited rather than silently passing."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.station_assignments')")
        assert cur.fetchone()[0] is None, "station_assignments exists again — revisit #5157"


def _seed_station_and_crew(cur):
    """Seed one active station plus a department AI and a rank-and-file agent.

    The isolated test DB is a SCHEMA clone with no seed rows, so these tests must
    build their own fixture rather than lean on production data (db_conn rolls back).

    The department MUST be one of the 17 values allowed by chk_agents_department —
    an invented one is rejected, and station_name has to equal it for the join to
    resolve. 'News & Media' is used deliberately: it is the one department with no
    bridge_stations row in production, so this fixture doubles as a demonstration
    of that gap being closed.
    """
    cur.execute(
        """
        INSERT INTO bridge_stations (station_code, station_name, color, icon,
                                     is_active, modules)
        VALUES ('T_NEWS', 'News & Media', '#00ffff', 'test',
                TRUE, ARRAY['t_test_module'])
        RETURNING id
        """
    )
    station_id = cur.fetchone()[0]
    for name, is_dept_ai in (("T.E.S.T.primary", True), ("T.E.S.T.aux", False)):
        cur.execute(
            """
            INSERT INTO agents (name, model, department, floor, worker_type,
                                shift_state, status, is_department_ai)
            VALUES (%s, 'qwen2.5:7b', 'News & Media', 'MEDIA', 'ai',
                    'active', 'active', %s)
            """,
            (name, is_dept_ai),
        )
    return station_id


def test_station_to_department_link_resolves(db_conn):
    """The replacement mapping must resolve a station to its department crew.

    Guards the substitution itself: if station_name and department drift apart,
    every station silently reports an empty crew — the same class of silent
    failure this fix removed.
    """
    with db_conn.cursor() as cur:
        _seed_station_and_crew(cur)
        cur.execute(
            """
            SELECT COUNT(a.id)
            FROM bridge_stations bs
            LEFT JOIN agents a
                   ON a.department = bs.station_name
                  AND a.worker_type = 'ai'
                  AND a.status = 'active'
            WHERE bs.is_active = TRUE AND bs.station_code = 'T_NEWS'
            """
        )
        crew = cur.fetchone()[0]

    assert crew == 2, f"station->department link resolved {crew} agents, expected 2"


def test_module_agent_lookup_returns_the_department_ai_first(db_conn):
    """The rewritten /api/module-agents query must run AND pick the director.

    The old query raised UndefinedTable and the endpoint swallowed it into
    {"agent_name": None}. This proves the replacement both executes and ranks the
    department AI above the rank-and-file — the station's primary.
    """
    with db_conn.cursor() as cur:
        _seed_station_and_crew(cur)
        cur.execute(
            """
            SELECT a.name AS agent_name, a.model, bs.station_code, a.status
            FROM bridge_stations bs
            JOIN agents a
              ON a.department = bs.station_name
             AND a.status = 'active'
             AND a.worker_type = 'ai'
            WHERE bs.is_active = TRUE AND %s = ANY(bs.modules)
            ORDER BY a.is_department_ai DESC NULLS LAST, a.tier ASC, a.id ASC
            LIMIT 1
            """,
            ("t_test_module",),
        )
        row = cur.fetchone()

    assert row is not None, "module resolved to no agent — the endpoint would report None again"
    assert row[0] == "T.E.S.T.primary", f"expected the department AI first, got {row[0]}"


def test_unknown_module_degrades_to_no_agent_not_an_error(db_conn):
    """A module with no station must return zero rows, never raise.

    News & Media currently has no bridge_stations row, so this path is live. The
    endpoint may legitimately answer "no agent"; what it must not do is throw.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.name
            FROM bridge_stations bs
            JOIN agents a
              ON a.department = bs.station_name
             AND a.status = 'active'
             AND a.worker_type = 'ai'
            WHERE bs.is_active = TRUE AND %s = ANY(bs.modules)
            LIMIT 1
            """,
            ("module_that_does_not_exist",),
        )
        assert cur.fetchone() is None
