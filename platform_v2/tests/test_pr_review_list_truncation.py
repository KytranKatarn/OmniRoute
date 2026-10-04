"""PR Review list — the count/truncation contract added with #3623.

Why these exist: the listing is `LIMIT`-capped, and the UI only ever receives ROWS. A
bare `200` on screen is indistinguishable from "all 200 of them", which is exactly how a
capped list got read as data loss on 2026-10-04 with 3,364 PRs archived.

So the route now reports `total` and `truncated`. That only helps if the count cannot
DRIFT from the rows it describes — which is the property these tests actually pin down,
along with the filter handling that decides whether a PR appears at all.

`count_reviews` and `list_reviews` build their WHERE clauses in two separate functions.
That duplication is the actual risk: someone adds a filter to one and not the other and
the banner confidently reports a wrong number. `test_count_shares_list_where_clause`
exists specifically to fail when that happens.

No database: the cursor is faked and the `database` module is injected, following
tests/test_approval_categories.py. These run in well under a second.
"""

import sys
import types
import unittest
from unittest import mock


def _load_service():
    """Import pr_review_service fresh.

    It does `from database import get_db_cursor` at MODULE level, so the name is bound
    once at import. Patching sys.modules afterwards is therefore too late: the service
    keeps the real function. The module has to be imported inside the patch, and dropped
    from sys.modules so the next test re-imports it against its own fake.
    """
    sys.modules.pop("tools.repair_bay.services.pr_review_service", None)
    from tools.repair_bay.services import pr_review_service as svc

    return svc


def _cursor(returning):
    """Cursor stub. `returning` is what fetchone() yields for the COUNT query."""
    cur = mock.MagicMock()
    seen = {"sql": None, "params": None}

    def execute(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params

    cur.execute.side_effect = execute
    cur.fetchone.side_effect = lambda: returning
    cur.fetchall.side_effect = lambda: []
    cur.seen = seen
    return cur


class _Ctx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return (mock.MagicMock(), self.cur)

    def __exit__(self, *a):
        return False


def _run_with_fake_db(cur, *args, **kwargs):
    """Call a service function with `get_db_cursor` faked.

    Patches the name WHERE IT IS USED, on the service module itself. Two earlier attempts
    failed and both are worth recording:

    - faking `sys.modules["database"]` — the service does `from database import
      get_db_cursor` at module level, and a fake missing `_get_db_password` (imported by
      github_routes) breaks the chain, so the real module is used instead.
    - popping the service from `sys.modules` first — `from package import name` returns
      the attribute CACHED on the parent package, so the pop does not force a re-import.

    Either way the test silently counted rows in the real, schema-only, EMPTY test
    database and returned 0 — a green-looking test measuring nothing. `mock.patch.object`
    on the bound name has no import-order dependency at all.
    """
    svc = _load_service()
    with mock.patch.object(svc, "get_db_cursor", lambda commit=False: _Ctx(cur)):
        return getattr(svc, args[0])(*args[1:], **kwargs)


class TestCountReviews(unittest.TestCase):
    """The COUNT must mirror list_reviews' filters exactly."""

    def test_returns_the_counted_total(self):
        svc = _load_service()
        cur = _cursor({"n": 3364})
        out = _run_with_fake_db(cur, "count_reviews")
        self.assertEqual(out, 3364)

    def test_accepts_a_tuple_row(self):
        """Real psycopg2 rows can arrive as tuples under a plain cursor. int() it."""
        svc = _load_service()
        cur = _cursor((774,))
        self.assertEqual(_run_with_fake_db(cur, "count_reviews"), 774)

    def test_missing_count_is_zero_not_a_crash(self):
        """A COUNT that somehow yields nothing must not raise inside the list route."""
        svc = _load_service()
        cur = _cursor(None)
        self.assertEqual(_run_with_fake_db(cur, "count_reviews"), 0)

    def test_state_filter_is_parameterised_not_interpolated(self):
        svc = _load_service()
        cur = _cursor({"n": 5})
        _run_with_fake_db(cur, "count_reviews", state="merged")
        self.assertIn("state = %s", cur.seen["sql"])
        self.assertIn("merged", cur.seen["params"])
        # The value must never be pasted into the SQL text.
        self.assertNotIn("'merged'", cur.seen["sql"])

    def test_both_filters_apply_together(self):
        svc = _load_service()
        cur = _cursor({"n": 2})
        _run_with_fake_db(cur, "count_reviews", state="open", review_status="reviewed")
        self.assertIn("state = %s", cur.seen["sql"])
        self.assertIn("review_status = %s", cur.seen["sql"])
        self.assertEqual(sorted(cur.seen["params"]), ["open", "reviewed"])

    def test_no_filters_selects_everything(self):
        svc = _load_service()
        cur = _cursor({"n": 6285})
        _run_with_fake_db(cur, "count_reviews")
        sql = cur.seen["sql"]
        self.assertIn("COUNT(*)", sql)
        self.assertNotIn("state =", sql)
        self.assertNotIn("review_status =", sql)

    def test_count_shares_list_where_clause(self):
        """THE invariant. If a filter is added to one function and not the other, the
        pane reports a total that does not describe the rows beside it — a confident,
        wrong number, which is worse than the silent cap this replaced."""
        svc = _load_service()
        for kwargs in (
            {},
            {"state": "open"},
            {"review_status": "reviewed"},
            {"state": "merged", "review_status": "reviewed"},
        ):
            with self.subTest(filters=kwargs):
                count_cur = _cursor({"n": 1})
                _run_with_fake_db(count_cur, "count_reviews", **kwargs)
                count_sql = count_cur.seen["sql"]
                count_params = list(count_cur.seen["params"] or [])

                list_cur = mock.MagicMock()
                list_cur.seen = {"sql": None, "params": None}

                def _exec(sql, params=None):
                    list_cur.seen["sql"] = sql
                    list_cur.seen["params"] = params

                list_cur.execute.side_effect = _exec
                list_cur.fetchall.side_effect = lambda: []
                _run_with_fake_db(list_cur, "list_reviews", limit=1, **kwargs)

                where_count = count_sql.split("WHERE", 1)[-1]
                where_list = list_cur.seen["sql"].split("WHERE", 1)[-1]
                # Strip the trailing verbs, which differ by design (COUNT vs SELECT).
                self.assertEqual(
                    _clause(where_count),
                    _clause(where_list),
                    f"count_reviews and list_reviews disagree on filters {kwargs}",
                )
                # list_reviews always appends `limit` LAST, so its trailing param is not
                # a filter. Comparing raw param lists would fail on every case purely
                # because the two queries legitimately differ there.
                list_params = list(list_cur.seen["params"] or [])
                self.assertEqual(
                    sorted(count_params),
                    sorted(list_params[:-1]),
                    f"count_reviews and list_reviews bind different filter params for {kwargs}",
                )


def _clause(where_tail):
    """The filter portion of a WHERE clause, without the trailing ORDER/LIMIT/GROUP."""
    for verb in ("ORDER BY", "GROUP BY", "LIMIT"):
        where_tail = where_tail.split(verb)[0]
    return " ".join(where_tail.split())


class TestTruncationContract(unittest.TestCase):
    """What the route promises the pane, asserted against the route source.

    The route is one `jsonify(payload)` behind decorators that need a live request, so
    these check the contract textually. They are a tripwire against someone dropping a
    key while refactoring — not a substitute for the browser smoke check, which is what
    actually proves the banner appears.
    """

    @classmethod
    def setUpClass(cls):
        from tests.repo_root import platform_root

        path = platform_root() / "tools" / "repair_bay" / "github_routes.py"
        assert path.exists(), f"github_routes.py not reachable at {path}"
        cls.src = path.read_text(encoding="utf-8")

    def test_route_reports_total_and_truncation(self):
        self.assertIn('"total": total', self.src)
        self.assertIn('"truncated": total > len(result)', self.src)
        self.assertIn('"limit": limit', self.src)

    def test_route_never_fails_the_listing_over_a_count(self):
        """A COUNT failure must degrade to len(result), not 500 the whole tab."""
        self.assertIn("except Exception as exc", self.src)
        self.assertIn("total = len(result)", self.src)

    def test_coderabbit_endpoint_sources_from_body_not_clean(self):
        """Regression guard for the NameError #3620 shipped: `clean` is read before it is
        assigned there, so every CodeRabbit request raised and the pane showed
        "(No CodeRabbit review)" instead of an error."""
        block = self.src.split("def forge_pr_coderabbit(", 1)[-1].split("@bp.route(", 1)[0]
        self.assertIn('re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)', block)
        self.assertNotIn('re.sub(r"<!--.*?-->", "", clean, flags=re.DOTALL)', block)

    def test_codex_endpoint_reads_the_reviews_collection(self):
        """CODEX posts via `gh pr review --comment`, which is /pulls/N/reviews. Reading
        issue comments (right for CodeRabbit) found nothing, every time."""
        block = self.src.split("def forge_pr_codex(", 1)[-1]
        self.assertIn("/pulls/{pr_number}/reviews", block)
        self.assertNotIn("/issues/{pr_number}/comments", block)


if __name__ == "__main__":
    unittest.main()
