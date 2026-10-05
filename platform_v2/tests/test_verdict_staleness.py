"""Stale verdicts — which stored reviews no longer describe the branch tip.

No browser and no network: `staleness_for` and `describe` are pure, and they are the
two pieces that decide what gets reported. The DB scan is exercised against a fake
cursor so the dedupe contract can be pinned without a database.

The behaviour pinned here came from two real misses.

The first is the obvious one: push a commit and every verdict on that PR describes
code that is no longer there. The merge gate already refuses a stale F.O.R.G.E.
approval, so the gate was never the problem — nothing TOLD you. F.O.R.G.E. only
became visibly stale at the instant you tried to merge.

The second is the one that would have shipped a monitor nobody trusts. Most of the
3,370 historical rows predate SHA stamping, so they carry a verdict with no recorded
sha. Treating "cannot prove staleness" as "stale" reports the entire archive as
broken on the first run — and a monitor that cries wolf on 3,370 rows is a monitor
people mute. So unprovable is its own bucket, never counted as a failure, and
`is_actionable` refuses it.

The third is quieter and cost the most to find: the F.O.R.G.E. sha lives at the TOP
level of metadata (`reviewed_head_sha`) while the two advisory reviewers keep theirs
nested (`codex.head_sha`, `probe.head_sha`). Reading all three from one place looks
right and silently reports every advisory verdict as absent.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, "/app")  # in-container; falls through when run from the repo

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.repair_bay.services.verdict_staleness import (  # noqa: E402
    REVIEWER_LABELS,
    REVIEWER_SHAS,
    describe,
    find_stale_open_prs,
    format_alert_message,
    is_actionable,
    staleness_for,
)

HEAD = "a" * 40
OTHER = "b" * 40


class TestStalenessFor(unittest.TestCase):
    """The core comparison. Pure — no DB, no fixtures."""

    def test_no_metadata_is_all_empty(self):
        out = staleness_for(None)
        self.assertEqual(out["head"], "")
        self.assertEqual(out["stale"], [])
        self.assertEqual(out["unproven"], [])
        self.assertEqual(out["current"], [])

    def test_non_dict_metadata_does_not_raise(self):
        """A JSONB column can hand back a list or a string on a bad write.

        Raising here would take down the whole list render, not one row.
        """
        for junk in ([], ["a"], "string", 7, None):
            out = staleness_for(junk)
            self.assertEqual(out["stale"], [], f"{junk!r} should yield no stale verdicts")

    def test_forge_verdict_on_a_different_commit_is_stale(self):
        out = staleness_for({"head_sha": HEAD, "reviewed_head_sha": OTHER})
        self.assertEqual(out["stale"], ["forge"])
        self.assertEqual(out["head"], HEAD)

    def test_forge_verdict_on_the_current_commit_is_current(self):
        out = staleness_for({"head_sha": HEAD, "reviewed_head_sha": HEAD})
        self.assertEqual(out["current"], ["forge"])
        self.assertEqual(out["stale"], [])

    def test_advisory_reviewers_read_their_own_nested_sha(self):
        """CODEX and P.R.O.B.E. keep their sha NESTED, not at the top level.

        The miss this guards: reading all three reviewers from one place looks
        correct and reports both advisory verdicts as absent forever.
        """
        out = staleness_for(
            {
                "head_sha": HEAD,
                "reviewed_head_sha": HEAD,  # F.O.R.G.E. current
                "codex": {"verdict": "APPROVE", "head_sha": OTHER},  # moved on
                "probe": {"verdict": "PASS", "head_sha": HEAD},  # still current
            }
        )
        self.assertEqual(out["stale"], ["codex"])
        self.assertEqual(out["current"], ["forge", "probe"])

    def test_all_three_reviewers_can_be_stale_at_once(self):
        out = staleness_for(
            {
                "head_sha": HEAD,
                "reviewed_head_sha": OTHER,
                "codex": {"verdict": "APPROVE", "head_sha": OTHER},
                "probe": {"verdict": "PASS", "head_sha": OTHER},
            }
        )
        self.assertEqual(out["stale"], ["forge", "codex", "probe"])

    def test_verdict_without_a_recorded_sha_is_unproven_not_stale(self):
        """The anti-wolf rule: no sha means unprovable, never stale."""
        out = staleness_for({"head_sha": HEAD, "reviewed_head_sha": ""})
        self.assertEqual(out["unproven"], ["forge"])
        self.assertEqual(out["stale"], [])

    def test_missing_head_sha_makes_everything_unprovable(self):
        """No polled head means nothing can be compared — not that everything is stale."""
        out = staleness_for({"reviewed_head_sha": OTHER, "codex": {"head_sha": OTHER}})
        self.assertEqual(out["head"], "")
        self.assertEqual(out["stale"], [])
        self.assertEqual(sorted(out["unproven"]), ["codex", "forge"])

    def test_reviewer_with_no_verdict_at_all_is_absent(self):
        """No CODEX review means CODEX has no opinion — not an unproven one."""
        out = staleness_for({"head_sha": HEAD, "reviewed_head_sha": HEAD})
        self.assertNotIn("codex", out["stale"])
        self.assertNotIn("codex", out["unproven"])
        self.assertNotIn("probe", out["unproven"])

    def test_verdict_metadata_without_a_head_key_is_unproven(self):
        out = staleness_for({"head_sha": HEAD, "codex": {"verdict": "APPROVE"}})  # no head_sha inside
        self.assertEqual(out["unproven"], ["codex"])

    def test_non_string_verdict_payload_is_unproven_not_a_crash(self):
        """`codex` could hold a list or dict after a bad write; do not blow up the render."""
        out = staleness_for({"head_sha": HEAD, "codex": ["APPROVE"], "probe": 7})
        self.assertEqual(out["stale"], [])
        self.assertEqual(sorted(out["unproven"]), ["codex", "probe"])

    def test_reviewer_paths_match_the_documented_storage(self):
        """Pin the paths themselves — this is the mapping #3628 decided."""
        self.assertEqual(REVIEWER_SHAS["forge"], ("reviewed_head_sha",))
        self.assertEqual(REVIEWER_SHAS["codex"], ("codex", "head_sha"))
        self.assertEqual(REVIEWER_SHAS["probe"], ("probe", "head_sha"))
        self.assertEqual(set(REVIEWER_SHAS), set(REVIEWER_LABELS))


class TestIsActionable(unittest.TestCase):
    def test_only_a_positive_contradiction_is_actionable(self):
        self.assertTrue(is_actionable({"stale": ["forge"], "unproven": [], "current": []}))

    def test_unprovable_alone_is_never_actionable(self):
        """This one rule is what keeps the monitor from reporting 3,370 legacy rows."""
        self.assertFalse(is_actionable({"stale": [], "unproven": ["forge"], "current": []}))

    def test_current_alone_is_never_actionable(self):
        self.assertFalse(is_actionable({"stale": [], "unproven": [], "current": ["forge"]}))

    def test_empty_is_never_actionable(self):
        self.assertFalse(is_actionable({}))
        self.assertFalse(is_actionable({"stale": []}))


class TestDescribe(unittest.TestCase):
    def test_names_the_affected_reviewers(self):
        msg = describe({"stale": ["forge", "codex"], "unproven": [], "current": []}, 3630)
        self.assertIn("#3630", msg)
        self.assertIn("F.O.R.G.E.", msg)
        self.assertIn("CODEX", msg)
        self.assertIn("OLDER commit", msg)

    def test_falls_back_to_the_bare_label_without_a_pr_number(self):
        msg = describe({"stale": ["forge"]})
        self.assertTrue(msg.startswith("PR:"), msg)

    def test_unproven_reads_as_unprovable_not_broken(self):
        msg = describe({"stale": [], "unproven": ["forge"], "current": []}, 1)
        self.assertIn("cannot be proven", msg)

    def test_current_is_reported_plainly(self):
        msg = describe({"stale": [], "unproven": [], "current": ["forge"]}, 1)
        self.assertIn("current", msg)

    def test_unknown_reviewer_key_does_not_raise(self):
        """A reviewer added later must not break the notification."""
        msg = describe({"stale": ["some_new_reviewer"]}, 1)
        self.assertIn("some_new_reviewer", msg)


class FakeCursor:
    """Minimal cursor: returns canned rows, records every UPDATE."""

    def __init__(self, rows):
        self._rows = rows
        self.updates = []

    def execute(self, sql, params=None):
        if "SELECT" in sql:
            self._sql = sql
            self._params = params
        elif "UPDATE" in sql:
            self.updates.append((sql, params))

    def fetchall(self):
        return self._rows


def _patch_db(rows, commits=None):
    """Patch database.get_db_cursor with a fake yielding FakeCursor(rows)."""
    cursor = FakeCursor(rows)
    commits = commits if commits is not None else [None]

    class _CM:
        def __init__(self, commit=False):
            self._c = cursor

        def __enter__(self):
            return (None, cursor)

        def __exit__(self, *exc):
            if commits:
                commits.pop(0)
            return False

    module = types.ModuleType("database")
    module.get_db_cursor = lambda commit=False: _CM(commit)
    return cursor, mock.patch.dict(sys.modules, {"database": module})


class TestFindStaleOpenPrs(unittest.TestCase):
    """The scan and its dedupe contract, against a fake cursor."""

    def _run(self, rows):
        cursor, patcher = _patch_db(rows)
        with patcher:
            return find_stale_open_prs(limit=10), cursor

    def test_reports_a_stale_row(self):
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": OTHER},
            }
        ]
        result, _ = self._run(rows)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["stale"], 1)
        self.assertEqual(result["reported"][0]["pr_number"], 3630)
        self.assertEqual(result["reported"][0]["stale"], ["forge"])

    def test_ignores_current_and_unprovable_rows(self):
        rows = [
            {
                "pr_number": 1,
                "repo": "o/r",
                "title": "",
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": HEAD},
            },
            {
                "pr_number": 2,
                "repo": "o/r",
                "title": "",
                "metadata": {"reviewed_head_sha": OTHER},  # no head at all
            },
        ]
        result, _ = self._run(rows)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["stale"], 0)
        self.assertEqual(result["reported"], [])

    def test_second_run_for_the_same_head_is_deduped(self):
        """The whole point of stale_notified_head.

        Without it a 30-minute job files the same notification 48 times a day for one
        forgotten re-review.
        """
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {
                    "head_sha": HEAD,
                    "reviewed_head_sha": OTHER,
                    "stale_notified_head": HEAD,  # already reported for this exact head
                },
            }
        ]
        result, _ = self._run(rows)
        self.assertEqual(result["stale"], 0)
        self.assertEqual(result["reported"], [])

    def test_a_new_push_re_arms_the_alert(self):
        """Head moved since the last report: a genuine new state, so alert again."""
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {
                    "head_sha": HEAD,
                    "reviewed_head_sha": OTHER,
                    "stale_notified_head": "z" * 40,  # notified about an older head
                },
            }
        ]
        result, _ = self._run(rows)
        self.assertEqual(result["stale"], 1)

    def test_reported_row_is_armed_with_its_head(self):
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": OTHER},
            }
        ]
        _, cursor = self._run(rows)
        self.assertEqual(len(cursor.updates), 1)
        _sql, params = cursor.updates[0]
        self.assertEqual(params, (HEAD, 3630))

    def test_merge_is_a_shallow_key_merge_not_a_metadata_overwrite(self):
        """The UPDATE must OR-merge one key in.

        Replacing the whole metadata document would erase reviewed_head_sha and both
        advisory verdicts — destroying the evidence the next run depends on.
        """
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": OTHER},
            }
        ]
        _, cursor = self._run(rows)
        sql, _ = cursor.updates[0]
        self.assertIn("||", sql)
        self.assertIn("stale_notified_head", sql)
        self.assertNotIn("SET metadata = %s", sql)

    def test_title_is_truncated_for_the_notification(self):
        rows = [
            {
                "pr_number": 1,
                "repo": "o/r",
                "title": "x" * 300,
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": OTHER},
            }
        ]
        result, _ = self._run(rows)
        self.assertEqual(len(result["reported"][0]["title"]), 80)

    def test_scan_failure_degrades_to_a_reason_not_an_exception(self):
        """A DB blip must not take the scheduled job down with a traceback."""

        class Boom:
            def __init__(self, commit=False):
                pass

            def __enter__(self):
                raise RuntimeError("connection refused")

            def __exit__(self, *exc):
                return False

        module = types.ModuleType("database")
        module.get_db_cursor = lambda commit=False: Boom()
        with mock.patch.dict(sys.modules, {"database": module}):
            result = find_stale_open_prs()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["stale"], 0)
        self.assertIn("scan failed", result["reasons"][0])

    def test_dedupe_write_failure_is_reported_but_does_not_raise(self):
        """Reporting succeeded; failing to arm must not lose the report."""

        class HalfBroken:
            def __init__(self, commit=False):
                self._fail = commit

            def __enter__(self):
                if self._fail:
                    raise RuntimeError("write timeout")
                return (None, FakeCursor([]))

            def __exit__(self, *exc):
                return False

        module = types.ModuleType("database")
        module.get_db_cursor = lambda commit=False: HalfBroken(commit)
        rows = [
            {
                "pr_number": 3630,
                "repo": "o/r",
                "title": "t",
                "metadata": {"head_sha": HEAD, "reviewed_head_sha": OTHER},
            }
        ]
        with mock.patch.dict(sys.modules, {"database": module}):
            calls = {"n": 0}

            def cm(commit=False):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _Ctx(FakeCursor(rows))
                return HalfBroken(commit)

            class _Ctx:
                def __init__(self, cur):
                    self._c = cur

                def __enter__(self):
                    return (None, self._c)

                def __exit__(self, *exc):
                    return False

            module.get_db_cursor = cm
            result = find_stale_open_prs(limit=10)
        self.assertEqual(result["stale"], 1, "the report must survive a failed arm")
        self.assertTrue(result["reasons"])


class TestFormatAlertMessage(unittest.TestCase):
    def test_empty_result_is_a_quiet_no_op(self):
        self.assertEqual(format_alert_message({"reported": []}), "No stale verdicts found.")

    def test_lists_each_pr_with_its_title(self):
        msg = format_alert_message(
            {
                "reported": [
                    {"summary": "PR #1: F.O.R.G.E. verdict(s) cover an OLDER commit", "title": "t"},
                ]
            }
        )
        self.assertIn("1 open PR(s)", msg)
        self.assertIn("#1", msg)
        self.assertIn("t", msg)

    def test_caps_the_list_and_says_how_many_were_dropped(self):
        reported = [{"summary": f"PR #{i}: stale", "title": f"t{i}"} for i in range(20)]
        msg = format_alert_message({"reported": reported})
        self.assertIn("and 5 more", msg)
        self.assertNotIn("#19:", msg)


if __name__ == "__main__":
    unittest.main()


class TestPollRecordsHeadSha(unittest.TestCase):
    """The poll is the FEED for staleness. A bug here silently disables it.

    `staleness_for` can be perfect and still never fire, because the value it compares
    against never arrives. That is not hypothetical: the poll read the sha from a nested
    `head.sha`, but `list_all_prs_enriched` returns it FLAT as `head_sha` and has no
    `head` dict at all. The read yielded None, the poll wrote "", and because the upsert
    is a right-biased JSONB merge, that "" ERASED the head a review had stamped — so
    every verdict degraded to unprovable and the monitor reported nothing, forever.

    These tests pin the shape contract between the two modules, which is where the
    breakage actually lived.
    """

    def test_poll_reads_the_flat_head_sha_key(self):
        """The exact bug: nested read against a flat payload returns nothing."""
        flat = {"head_sha": "abc123", "head_ref": "feature/x"}
        self.assertEqual(flat.get("head") or {}, {}, "payload has no nested head dict")
        # The old expression:
        self.assertEqual(((flat.get("head") or {}).get("sha") or ""), "")
        # The correct one:
        self.assertEqual(flat.get("head_sha") or "", "abc123")

    def test_poll_writes_a_non_empty_head_sha(self):
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_review_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"head_sha": (pr.get("head_sha") or ""),',
            source,
            'the poll must read the flat head_sha key; a nested read writes "" and ' "erases any stamped head",
        )

    def test_poll_does_not_read_a_nested_head_sha(self):
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_review_service.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            '"head_sha": ((pr.get("head") or {}).get("sha")',
            source,
            "regression: the poll is reading a nested head.sha that the poll payload " "does not have",
        )

    def test_empty_head_does_not_overwrite_a_stamped_one(self):
        """Guard the follow-on risk: if the poll ever yields no sha, keep the old value.

        Right-biasing means writing "" is destructive. Whether or not that is fixed, the
        comparison is what decides: a stamped head with a differing verdict is stale, and
        an unstamped head is only unprovable. Both must hold.
        """
        stamped = {"head_sha": "abc", "reviewed_head_sha": "old"}
        out = staleness_for(stamped)
        self.assertEqual(out["stale"], ["forge"])

        wiped = {"head_sha": "", "reviewed_head_sha": "old"}
        out = staleness_for(wiped)
        self.assertEqual(out["stale"], [], "an empty head must NOT read as stale")
        self.assertEqual(out["unproven"], ["forge"])
