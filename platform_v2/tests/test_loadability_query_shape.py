"""The observer's query must AGGREGATE before it JOINs — not the other way round.

Found 2026-09-11 by watching the job never finish. `check_model_loadability` logged
"loadability: check starting" on schedule and then nothing: no completion line, no
persist warning, no exception. `pg_stat_activity` showed its SELECT `active` for
**8m46s** before it was cancelled by hand.

The cause was a LATERAL correlated to `scoped` — the RAW ROWS — with the GROUP BY
applied afterwards. A correlated LATERAL re-executes per OUTER ROW, so a 30-day
scan ran ~1,773 times (one per dispatch in the 3h window) to answer 14 questions
(one per node x model). Rewritten to group first and join a single grouped 30-day
CTE, the same statement measured **901ms** on the same data.

⚠️ WHY A SHAPE TEST AND NOT A TIMING TEST. Postgres 16 can rescue the bad form with
a Memoize node, and sometimes did: the identical statement measured 10-16s from
`archie_platform` and 8m46s in `archie_scheduler`. A timing assertion would
therefore pass on the broken query whenever the planner happened to memoize — it
would be a test that cannot fail when it matters. The SHAPE is the invariant; the
speed is a consequence of it.

(pytest also forces the empty `archie_test` DB, so a timing test would run against
zero rows and pass vacuously — see the `pytest live data is VACUOUS` note.)
"""

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "services" / "model_loadability_monitor.py"


def _sql(text: str) -> str:
    """The _SQL literal only — comments ABOUT the query must not satisfy a check
    that is supposed to be about the query. (Grepping my own prose instead of the
    code has produced three false passes in this module's history.)"""
    m = re.search(r'^_SQL = """(.*?)"""', text, re.S | re.M)
    assert m, "_SQL literal not found — the query has been restructured, re-verify by hand"
    return m.group(1)


def _source() -> str:
    if not SRC.exists():
        pytest.skip(f"{SRC} not reachable from this test root")
    return SRC.read_text()


class TestAggregateBeforeJoin:
    def test_the_success_stats_are_not_a_correlated_lateral(self):
        """The defect itself. A LATERAL here is per-row by definition."""
        assert "LATERAL" not in _sql(_source()).upper(), (
            "the success stats are back on a correlated LATERAL — it re-executes "
            "once per raw row, which is how the job stopped completing (8m46s)"
        )

    def test_the_final_select_reads_the_grouped_cte_not_the_raw_rows(self):
        """`FROM scoped` in the outer SELECT is the shape that put thousands of
        rows on the driving side of the join. `FROM agg` is dozens."""
        sql = _sql(_source())
        tail = sql[sql.rindex("\nSELECT ") :]
        assert re.search(r"\bFROM\s+agg\b", tail), (
            "the outer SELECT no longer drives off the aggregated CTE — " f"found: {tail.strip()[:200]}"
        )
        assert not re.search(r"\bFROM\s+scoped\s+s\b", tail), "the outer SELECT is driving off the RAW rows again"

    def test_the_outer_select_does_not_group(self):
        """Grouping in the outer SELECT means the join ran on ungrouped rows —
        the whole defect, whatever the join is spelled as."""
        sql = _sql(_source())
        tail = sql[sql.rindex("\nSELECT ") :]
        assert "GROUP BY" not in tail.upper(), "the outer SELECT groups, so whatever it joined was joined per-row"

    def test_the_thirty_day_scan_is_grouped_once(self):
        """succ30 must be a grouped CTE, not something correlated to the outer row."""
        sql = _sql(_source())
        m = re.search(r"succ30 AS \((.*?)\n\)", sql, re.S)
        assert m, "succ30 CTE not found"
        body = m.group(1)
        assert "GROUP BY" in body.upper(), "succ30 does not group — it is per-row again"
        assert (
            "s.node_name" not in body and "a.node_name" not in body
        ), "succ30 references an outer alias — it is correlated, i.e. per-row"


class TestTheObserverCannotBlockForever:
    """An observer that can hang its caller is worse than no observer — the
    module's own contract. The rewrite makes a hang implausible; the timeout
    makes it impossible."""

    def test_load_rows_sets_a_statement_timeout(self):
        src = _source()
        body = src[src.index("def _load_rows") : src.index("_SETTING_LAST")]
        assert "statement_timeout" in body, "_load_rows can still block indefinitely"

    def test_the_timeout_is_transaction_scoped(self):
        """A bare `SET` would leak the timeout onto every later caller that gets
        this pooled connection. SET LOCAL is reverted with the transaction."""
        src = _source()
        body = src[src.index("def _load_rows") : src.index("_SETTING_LAST")]
        assert (
            "SET LOCAL statement_timeout" in body
        ), "the timeout is not SET LOCAL — it would leak into the connection pool"

    def test_the_timeout_is_generous_enough_to_be_a_backstop_not_a_limit(self):
        """901ms measured. A timeout near that would turn a slow-but-fine run into
        a failure; one far above it only ever catches a genuine hang."""
        m = re.search(r"_STATEMENT_TIMEOUT_MS\s*=\s*([\d_]+)", _source())
        assert m, "_STATEMENT_TIMEOUT_MS not found"
        assert int(m.group(1).replace("_", "")) >= 30_000
