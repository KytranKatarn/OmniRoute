"""/echo precomputed counts — the job, the reader, and the contract between them.

/echo used to run 14 full-text phrase queries PER REQUEST: ~42 s on Citadel (measured
2026-10-05), one gunicorn worker held the whole time, no rate limit on the route. The
counts are now computed daily by ingest/echo/phrase_counts.py into wtf.echo_phrase_counts
(migration 089) and the page only reads them.

The failure these tests exist for is quiet: a reader/job disagreement or an unfilled table
rendering as a page of confident ZEROS. Each guard below is mutation-checked against it.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytest

from consumer import echo_data
from ingest.echo import phrase_counts as pc
from shared import echo_phrases as ep

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 5)  # a Monday


# ── shared bucket arithmetic ────────────────────────────────────────────────
class TestBuckets:
    def test_week_and_day_windows_have_the_stated_length_and_end_today(self):
        w, d = ep.week_starts(TODAY), ep.day_starts(TODAY)
        assert len(w) == ep.SLOGAN_WINDOW_WEEKS and w[-1] == TODAY and all(x.weekday() == 0 for x in w)
        assert len(d) == ep.WORD_WINDOW_DAYS and d[-1] == TODAY

    def test_job_and_reader_enumerate_the_same_buckets_as_densify(self):
        # densify_* is what turns stored rows into the series the page draws. If the job
        # wrote different bucket dates, every lookup would miss and read as zero.
        stored = {b: i + 1 for i, b in enumerate(ep.week_starts(TODAY))}
        assert echo_data.densify_weekly(stored, today=TODAY) == list(range(1, 14))
        stored = {b: i + 1 for i, b in enumerate(ep.day_starts(TODAY))}
        assert echo_data.densify_daily(stored, today=TODAY) == list(range(1, 31))

    def test_plan_recomputes_everything_when_nothing_is_stored(self):
        win = ep.week_starts(TODAY)
        assert ep.plan_recompute(win, set()) == sorted(win)

    def test_plan_in_steady_state_recomputes_only_the_newest_two(self):
        win = ep.week_starts(TODAY)
        assert ep.plan_recompute(win, set(win)) == win[-2:]

    def test_plan_fills_a_gap_in_the_middle(self):
        win = ep.week_starts(TODAY)
        gap = win[4]
        assert gap in ep.plan_recompute(win, set(win) - {gap})

    def test_contiguous_fills_the_range_so_empty_buckets_become_explicit_zeros(self):
        a, b = dt.date(2026, 9, 7), dt.date(2026, 10, 5)
        got = pc.contiguous([a, b], dt.timedelta(weeks=1))
        assert got == [a + dt.timedelta(weeks=i) for i in range(5)]


# ── the SQL pass ────────────────────────────────────────────────────────────
class TestPassSql:
    def test_one_count_column_and_one_param_per_phrase(self):
        sql = pc.build_pass_sql("week", 3)
        assert [f":p{i}" for i in range(3)] == re.findall(r":p\d", sql)
        assert sql.count("COUNT(*) FILTER") == 3

    def test_tsvector_is_built_once_in_a_materialized_cte_not_per_phrase(self):
        sql = pc.build_pass_sql("day", 8)
        assert sql.count("to_tsvector(") == 1 and "MATERIALIZED" in sql

    def test_uses_the_same_text_expression_as_the_old_page_query(self):
        # Equal expression => equal counts. Verified on Citadel 2026-10-05: this pass and the
        # eight per-phrase queries both gave 365/456/223/181/138/162/67/57.
        assert "coalesce(title, '') || ' ' || coalesce(body, '')" in pc.build_pass_sql("week", 1)

    def test_suppressed_articles_are_excluded_like_before(self):
        assert "suppressed_reason IS NULL" in pc.build_pass_sql("week", 1)

    def test_grain_is_a_closed_set_because_it_is_interpolated(self):
        with pytest.raises(ValueError):
            pc.build_pass_sql("week'); DROP TABLE wtf.articles; --", 1)


# ── the job, against a recording fake engine ────────────────────────────────
class _Res:
    def __init__(self, rows): self._r = rows
    def all(self): return self._r


class _Conn:
    def __init__(self, eng): self.e = eng
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.e.calls.append((sql, params))
        if "FROM wtf.echo_phrase_counts" in sql and "GROUP BY bucket_start" in sql:
            return _Res([(b,) for b in self.e.present.get(params["k"], [])])
        if "WITH recent AS" in sql:
            return _Res(self.e.pass_rows.get("week" if "'week'" in sql else "day", []))
        return _Res([])


class _Engine:
    def __init__(self, present=None, pass_rows=None, boom=None):
        self.calls, self.present, self.pass_rows, self.boom = [], present or {}, pass_rows or {}, boom
    def connect(self): return _Conn(self)
    def begin(self):
        if self.boom:
            raise self.boom
        return _Conn(self)
    def upserts(self):
        return [p for sql, p in self.calls if "INSERT INTO wtf.echo_phrase_counts" in sql for p in p]
    def heartbeats(self):
        return [(sql, p) for sql, p in self.calls if "parliament.ingest_log" in sql]


class TestJob:
    def test_first_run_writes_every_phrase_for_every_bucket_with_explicit_zeros(self):
        eng = _Engine()  # nothing stored, no articles matched anywhere
        out = pc.run_echo_phrase_counts(eng, today=TODAY)
        rows = eng.upserts()
        n_slogan = len(ep.SLOGANS) * ep.SLOGAN_WINDOW_WEEKS
        n_word = len(ep.WORDS) * ep.WORD_WINDOW_DAYS
        assert len(rows) == n_slogan + n_word == out["upserted"]
        assert all(r["n"] == 0 for r in rows), "no match must be stored as a ZERO row, not omitted"

    def test_a_real_count_lands_on_the_right_phrase_and_bucket(self):
        wk = ep.week_starts(TODAY)[-1]
        counts = [0] * len(ep.SLOGANS); counts[2] = 41
        eng = _Engine(pass_rows={"week": [(wk, *counts)]})
        pc.run_echo_phrase_counts(eng, today=TODAY)
        hit = [r for r in eng.upserts() if r["k"] == "slogan" and r["b"] == wk and r["n"] == 41]
        assert [r["ph"] for r in hit] == [ep.SLOGANS[2][0]]

    def test_steady_state_recomputes_only_the_newest_buckets(self):
        eng = _Engine(present={"slogan": ep.week_starts(TODAY), "word": ep.day_starts(TODAY)})
        pc.run_echo_phrase_counts(eng, today=TODAY)
        assert {r["b"] for r in eng.upserts() if r["k"] == "slogan"} == set(ep.week_starts(TODAY)[-2:])
        assert {r["b"] for r in eng.upserts() if r["k"] == "word"} == set(ep.day_starts(TODAY)[-2:])

    def test_dry_run_writes_no_counts(self):
        eng = _Engine()
        out = pc.run_echo_phrase_counts(eng, today=TODAY, dry_run=True)
        assert eng.upserts() == [] and out["upserted"] == 0 and out["candidates"] > 0

    def test_heartbeat_on_success(self):
        eng = _Engine()
        pc.run_echo_phrase_counts(eng, today=TODAY)
        sql, p = eng.heartbeats()[-1]
        assert "records_upserted" in sql and p["t"] == "echo_phrase_counts" and p["u"] > 0

    def test_a_crash_is_swallowed_and_heartbeats_the_error_not_silence(self):
        # The job must never take the ingest loop down, and a failure must be VISIBLE.
        class Boom(_Engine):
            def begin(self_inner):
                if not getattr(self_inner, "_n", 0):
                    self_inner._n = 1
                    raise RuntimeError("db gone")
                return _Conn(self_inner)
        eng = Boom()
        out = pc.run_echo_phrase_counts(eng, today=TODAY)
        assert "db gone" in out["error"]
        sql, p = eng.heartbeats()[-1]
        assert "error" in sql and "db gone" in p["e"]


# ── the reader ──────────────────────────────────────────────────────────────
class _Rows:
    def __init__(self, rows): self._r = rows
    def mappings(self): return self
    def all(self): return self._r


class _StatusConn:
    def __init__(self, rows=None, boom=None): self.rows, self.boom = rows or [], boom
    def execute(self, stmt, params=None):
        if self.boom:
            raise self.boom
        return _Rows(self.rows)


def _full(end_w=TODAY, end_d=TODAY, stamp=dt.datetime(2026, 10, 5, 4, 0)):
    rows = [{"kind": "slogan", "phrase": p, "bucket_start": b, "computed_at": stamp}
            for p, _w, _c in ep.SLOGANS for b in ep.week_starts(end_w)]
    rows += [{"kind": "word", "phrase": p, "bucket_start": b, "computed_at": stamp}
             for _l, p, _c in ep.WORDS for b in ep.day_starts(end_d)]
    return rows


class TestCountsStatus:
    def test_complete_table_is_ready_and_reports_as_of(self):
        st = echo_data.counts_status(_StatusConn(_full()), "wtf", today=TODAY)
        assert st["ready"] and st["as_of"] == dt.datetime(2026, 10, 5, 4, 0)
        assert st["slogan_end"] == TODAY and st["word_end"] == TODAY

    def test_an_empty_table_is_not_ready_never_zeros(self):
        assert echo_data.counts_status(_StatusConn([]), "wtf", today=TODAY)["ready"] is False

    def test_a_missing_table_is_not_ready_and_does_not_raise(self):
        st = echo_data.counts_status(_StatusConn(boom=RuntimeError('relation "wtf.echo_phrase_counts" does not exist')),
                                     "wtf", today=TODAY)
        assert st["ready"] is False and st["as_of"] is None

    def test_one_missing_bucket_in_the_window_makes_it_not_ready(self):
        rows = _full()
        victim = ep.week_starts(TODAY)[3]
        rows = [r for r in rows if not (r["kind"] == "slogan" and r["bucket_start"] == victim
                                        and r["phrase"] == ep.SLOGANS[0][0])]
        # the anchor is the newest bucket common to ALL phrases, and the window behind it has a hole
        assert echo_data.counts_status(_StatusConn(rows), "wtf", today=TODAY)["ready"] is False

    def test_a_phrase_with_no_rows_at_all_blocks_ready(self):
        rows = [r for r in _full() if r["phrase"] != ep.WORDS[0][1]]
        assert echo_data.counts_status(_StatusConn(rows), "wtf", today=TODAY)["ready"] is False

    def test_window_is_anchored_on_the_newest_computed_bucket_not_on_today(self):
        # Job ran yesterday; it is now just past midnight. Must still render (last complete
        # data, labelled by date), not flip to "refreshing" until the next run.
        yesterday = TODAY - dt.timedelta(days=1)
        st = echo_data.counts_status(_StatusConn(_full(end_w=ep.week_starts(yesterday)[-1], end_d=yesterday)),
                                     "wtf", today=TODAY)
        assert st["ready"] and st["word_end"] == yesterday


class TestReadersUseTheStoredTable:
    def test_fetchers_read_the_table_not_the_articles_full_text(self):
        seen = []
        class C:
            def execute(self, stmt, params=None):
                seen.append(str(stmt)); return _Rows([])
        echo_data.fetch_weekly_counts(C(), "wtf", "Elbows up")
        echo_data.fetch_daily_counts(C(), "wtf", "trump")
        for sql in seen:
            assert "echo_phrase_counts" in sql
            assert "to_tsvector" not in sql and "phraseto_tsquery" not in sql, (
                "a request-time full-text query is the ~42 s bug this table exists to remove")


class TestRouteAndTemplate:
    def test_route_checks_status_on_its_own_connection_and_skips_builders_when_not_ready(self):
        src = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
        body = src[src.index("def echo("):src.index('@bp.get("/methodology")')]
        assert "counts_status(" in body and 'counts["ready"]' in body
        assert body.index("counts_status(") < body.index("build_slogan_rows(")
        assert "else:\n        slogans, words = [], []" in body

    def test_not_ready_shows_a_notice_and_ready_shows_the_as_of_date(self):
        from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
        env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block content %}{% endblock %}"}),
                                               FileSystemLoader(str(ROOT / "consumer" / "templates"))]),
                          autoescape=select_autoescape(["html"]))
        base = dict(slogans=[], words=[], most_used=None, fading=None, total_uses=0,
                    window_weeks=13, word_window_days=30, is_subscriber=False)
        t = env.get_template("echo.html")
        assert "being refreshed" in t.render(**base, counts_ready=False, counts_as_of=None)
        ok = t.render(**base, counts_ready=True, counts_as_of=dt.datetime(2026, 10, 5, 4, 0))
        assert "Counts as of Oct 5" in ok and "being refreshed" not in ok
        assert "being refreshed" not in t.render(**base)  # callers that omit the flags are unchanged


# ── wiring ──────────────────────────────────────────────────────────────────
class TestWiring:
    def test_migration_stores_zeros_and_logs_itself(self):
        sql = (ROOT / "migrations" / "089_echo_phrase_counts.sql").read_text(encoding="utf-8")
        assert "PRIMARY KEY (kind, phrase, bucket_start)" in sql and "CHECK (n >= 0)" in sql
        assert "INSERT INTO public.schema_migrations" in sql and "'089'" in sql
        assert "ON CONFLICT (version) DO NOTHING" in sql and "IF NOT EXISTS" in sql

    def test_job_is_scheduled_daily_in_the_ingest_loop(self):
        src = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
        assert "run_echo_phrase_counts" in src and "_last_echo_day" in src

    def test_job_is_watched_by_the_drift_guard_and_required(self):
        from ingest.parliament.drift_guard import _MAX_AGE_DAYS, _REQUIRED_TASKS
        assert "echo_phrase_counts" in _MAX_AGE_DAYS and "echo_phrase_counts" in _REQUIRED_TASKS
        assert _MAX_AGE_DAYS["echo_phrase_counts"] <= 7, "a DAILY job needs a window in days, not weeks"
