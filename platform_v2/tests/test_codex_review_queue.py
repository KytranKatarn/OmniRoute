"""Pin the CODEX review queue: what the Repair Bay button writes, and what it refuses.

The button used to be specified as an ssh call from the platform. It cannot work that
way, and both halves were verified rather than assumed:

* the container cannot ssh to its own host — every address returns
  ``Permission denied (publickey)``;
* ``/mnt/archie_brain`` is mounted READ-ONLY in the container, so it cannot write a
  request into the repo.

So requests go through a spool on ``/mnt/archie_sandbox``, the one path writable from
both sides, and the host-side runner picks them up. These tests use a temp spool: the
real one is a shared mount and a test must not write into it.

Three properties that matter:

1. THE PR NUMBER IS VALIDATED BEFORE IT REACHES THE SPOOL. It is the only value that
   ends up interpolated into a shell command on the host. Anything non-numeric, zero,
   negative, bool, float or None is refused — not sanitised, refused.
2. IT NEVER RAISES INTO A REQUEST. The endpoint calls these from a Flask view; a
   filesystem failure must become a 503-shaped dict, not a 500 traceback.
3. ONE QUEUE ENTRY PER PR. A double-click must not queue two reviews of the same head.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

# Loaded by FILE PATH, not as `tools.repair_bay.services.codex_review_service`.
#
# Importing the package would run tools/repair_bay/__init__.py, which imports the Flask
# app and therefore conftest's whole test-database fixture — and that fixture cannot
# restore in this environment (the platform image ships pg_dump 17 against a PG 16
# server, so the restore dies on `transaction_timeout`; it fails identically on clean
# main). None of that is relevant here: this service imports only the standard library
# and touches one directory. Loading it directly keeps the test hermetic and runnable
# anywhere, which is the correct shape for a unit test.
SERVICE_PATH = Path(__file__).resolve().parent.parent / "tools" / "repair_bay" / "services" / "codex_review_service.py"


def _load_service(spool: Path):
    """(Re)import the service with CODEX_REVIEW_QUEUE pointed at a temp dir.

    The module reads QUEUE_DIR at import time, so it must be reloaded per spool rather
    than monkeypatched after the fact.
    """
    os.environ["CODEX_REVIEW_QUEUE"] = str(spool)
    spec = importlib.util.spec_from_file_location("codex_review_service_under_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueueTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Path(self._tmp.name) / "queue"
        self.svc = _load_service(self.spool)
        # CODEX REVIEW FIX: enqueue no longer CREATES the spool — it refuses when the
        # directory is absent, because mkdir(parents=True) used to fabricate a spool that
        # existed only inside the container and that the host runner could never see.
        # Creating it is a deployment step, so the tests stand it up explicitly.
        (self.spool / "pending").mkdir(parents=True)
        (self.spool / "done").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("CODEX_REVIEW_QUEUE", None)


class TestPrValidation(QueueTestBase):
    def test_accepts_positive_ints_and_numeric_strings(self):
        for value, want in [(3613, 3613), ("3613", 3613), (" 3613 ", 3613), (1, 1)]:
            with self.subTest(value=value):
                self.assertEqual(self.svc._valid_pr(value), want)

    def test_refuses_everything_that_is_not_a_positive_integer(self):
        # bool is an int subclass — True must not become PR #1.
        for value in (
            None,
            True,
            False,
            0,
            -1,
            "-5",
            "0",
            "12; rm -rf /",
            "3.5",
            3.5,
            "abc",
            "",
            "  ",
            [],
            {},
            1e3,
            "0x10",
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.svc._valid_pr(value), f"{value!r} must be refused, not coerced")

    def test_enqueue_refuses_a_hostile_pr_without_writing_anything(self):
        result = self.svc.enqueue_codex_review("3613; rm -rf /")
        self.assertFalse(result["success"])
        self.assertIn("invalid PR number", result["error"])
        # Nothing may have been created — a refusal must not leave a partial request.
        self.assertEqual(list(self.spool.rglob("*.json")), [])


class TestEnqueue(QueueTestBase):
    def test_writes_a_well_formed_request(self):
        result = self.svc.enqueue_codex_review(3613, repo="KytranKatarn/archie-platform")
        self.assertTrue(result["success"])
        files = list(self.svc.PENDING_DIR.glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text())
        self.assertEqual(data["kind"], "codex_review")  # the runner checks this
        self.assertEqual(data["pr"], 3613)
        self.assertFalse(data["dry_run"])
        self.assertIn("requested_at", data)

    def test_dry_run_is_recorded_for_the_runner(self):
        self.svc.enqueue_codex_review(7, dry_run=True)
        data = json.loads(next(self.svc.PENDING_DIR.glob("*.json")).read_text())
        self.assertTrue(data["dry_run"])

    def test_no_temporary_files_are_left_behind(self):
        """The runner polls the same dir; a stray .tmp must not look like a request."""
        self.svc.enqueue_codex_review(11)
        leftovers = [p.name for p in self.svc.PENDING_DIR.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_second_request_for_same_pr_is_refused(self):
        first = self.svc.enqueue_codex_review(3613)
        self.assertTrue(first["success"])
        second = self.svc.enqueue_codex_review(3613)
        self.assertFalse(second["success"])
        self.assertEqual(second["request_id"], first["request_id"])
        self.assertIn("already has a review queued", second["error"])
        self.assertEqual(len(list(self.svc.PENDING_DIR.glob("*.json"))), 1)

    def test_different_prs_both_queue(self):
        self.assertTrue(self.svc.enqueue_codex_review(1)["success"])
        self.assertTrue(self.svc.enqueue_codex_review(2)["success"])
        self.assertEqual(len(list(self.svc.PENDING_DIR.glob("*.json"))), 2)

    def test_missing_spool_is_refused_not_created(self):
        """The regression this pins: a missing mount must NOT be papered over.

        Before the fix, enqueue ran mkdir(parents=True) and then probed writability, so
        it reported success for a directory that existed only inside the container's own
        filesystem. Reproduced live: the container created the spool root-owned 0755 and
        the host runner then died with "cannot create ... need write access".
        """
        absent = Path(self._tmp.name) / "never-created"
        svc = _load_service(absent)
        self.assertFalse(svc.queue_dir_available())
        result = svc.enqueue_codex_review(3613)
        self.assertFalse(result["success"], "a missing spool must not report success")
        self.assertIn("queue not available", result["error"])
        self.assertFalse(absent.exists(), "enqueue must NOT create the spool itself")

    def test_queue_dir_available_is_true_for_a_real_spool(self):
        self.assertTrue(self.svc.queue_dir_available())
        self.assertTrue(self.svc.enqueue_codex_review(5)["success"])

    def test_unwritable_queue_returns_an_error_not_an_exception(self):
        """A 500 traceback from an unwritable path would be the wrong failure mode."""
        import stat

        blocked = Path(self._tmp.name) / "ro"
        (blocked / "pending").mkdir(parents=True)
        (blocked / "done").mkdir(parents=True)
        os.chmod(blocked / "pending", stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write
        try:
            svc = _load_service(blocked)
            result = svc.enqueue_codex_review(3613)
            self.assertFalse(result["success"])
            self.assertIn("queue not available", result["error"])
        finally:
            os.chmod(blocked / "pending", stat.S_IRWXU)


class TestStatus(QueueTestBase):
    def test_none_when_nothing_requested(self):
        self.assertEqual(self.svc.codex_review_status(3613)["status"], "none")

    def test_pending_while_queued(self):
        rid = self.svc.enqueue_codex_review(3613)["request_id"]
        self.assertEqual(self.svc.codex_review_status(3613)["status"], "pending")
        self.assertEqual(self.svc.codex_review_status(3613)["request_id"], rid)

    def test_reports_the_newest_completed_result(self):
        # No enqueue() here: a pending request legitimately shadows earlier results
        # (that precedence is asserted separately below). This test is about ordering
        # among COMPLETED runs.
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        for rid, rc in (("1000-3613", 1), ("2000-3613", 0)):
            (self.svc.DONE_DIR / f"{rid}.json").write_text(
                json.dumps(
                    {
                        "id": rid,
                        "pr": 3613,
                        "rc": rc,
                        "status": "ok" if rc == 0 else "error",
                    }
                ),
                encoding="utf-8",
            )
        status = self.svc.codex_review_status(3613)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["request_id"], "2000-3613")

    def test_pending_wins_over_a_previous_result(self):
        """A fresh request must not be reported as finished because an older one was."""
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        (self.svc.DONE_DIR / "1000-3613.json").write_text(
            json.dumps({"id": "1000-3613", "pr": 3613, "rc": 0, "status": "ok"}),
            encoding="utf-8",
        )
        self.svc.enqueue_codex_review(3613)
        self.assertEqual(self.svc.codex_review_status(3613)["status"], "pending")

    def test_results_for_other_prs_are_ignored(self):
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        (self.svc.DONE_DIR / "1000-99.json").write_text(
            json.dumps({"id": "1000-99", "pr": 99, "rc": 0, "status": "ok"}),
            encoding="utf-8",
        )
        self.assertEqual(self.svc.codex_review_status(3613)["status"], "none")

    def test_malformed_result_files_are_skipped_not_fatal(self):
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        (self.svc.DONE_DIR / "garbage.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.svc.codex_review_status(3613)["status"], "none")

    def test_log_is_returned_and_truncated(self):
        self.svc.enqueue_codex_review(42)
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        log = self.svc.DONE_DIR / "big.log"
        log.write_text("X" * 50_000, encoding="utf-8")
        (self.svc.DONE_DIR / "1000-42.json").write_text(
            json.dumps(
                {
                    "id": "1000-42",
                    "pr": 42,
                    "rc": 0,
                    "status": "ok",
                    "log": str(log),
                }
            ),
            encoding="utf-8",
        )
        text = self.svc.read_review_log(42, max_chars=1000)
        self.assertIsNotNone(text)
        self.assertEqual(len(text), 1000)  # bounded, never the whole file

    def test_non_object_json_in_the_spool_is_skipped_not_fatal(self):
        """CODEX REVIEW FIX: `[]`, `"x"` and `5` are valid JSON.

        json.loads() succeeded on them and the very next line, data.get(), raised
        AttributeError — aborting the whole directory scan, so every valid result that
        sorted after the bad file became invisible.
        """
        for payload, label in (
            ("[]", "array"),
            ('"x"', "string"),
            ("5", "number"),
            ("null", "null"),
            ("true", "bool"),
        ):
            with self.subTest(payload=payload):
                self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
                # Sorts BEFORE the valid result, which is the ordering that hid it.
                (self.svc.DONE_DIR / "0000-bad.json").write_text(payload, encoding="utf-8")
                (self.svc.DONE_DIR / "9000-good.json").write_text(
                    json.dumps({"id": "9000-good", "pr": 3613, "rc": 0, "status": "ok"}),
                    encoding="utf-8",
                )
                status = self.svc.codex_review_status(3613)
                self.assertEqual(status["status"], "ok", f"a {label} entry hid the real result")

    def test_non_object_json_in_pending_does_not_break_duplicate_detection(self):
        for payload in ("[]", '"x"', "5"):
            with self.subTest(payload=payload):
                # Clear between iterations: the previous one's real request would
                # otherwise be (correctly) refused as a duplicate and mask the result.
                for stale in self.svc.PENDING_DIR.glob("*.json"):
                    stale.unlink()
                (self.svc.PENDING_DIR / "0000-bad.json").write_text(payload, encoding="utf-8")
                second = self.svc.enqueue_codex_review(3613)
                self.assertTrue(second["success"])
                self.assertFalse(
                    self.svc.enqueue_codex_review(3613)["success"],
                    f"a {payload} entry defeated duplicate detection",
                )

    def test_non_string_log_value_is_ignored_not_raised(self):
        """CODEX REVIEW FIX: {"pr":42,"log":123} raised TypeError in Path(log).

        The handler caught OSError only, so the GET endpoint returned HTTP 500.
        """
        self.svc.DONE_DIR.mkdir(parents=True, exist_ok=True)
        (self.svc.DONE_DIR / "1000-42.json").write_text(
            json.dumps(
                {
                    "id": "1000-42",
                    "pr": 42,
                    "rc": 0,
                    "status": "ok",
                    "log": 123,
                }
            ),
            encoding="utf-8",
        )
        self.assertIsNone(self.svc.read_review_log(42))
        self.assertEqual(self.svc.codex_review_status(42)["status"], "ok")

    def test_request_ids_are_unique_within_one_second(self):
        """CODEX REVIEW FIX: int(time.time()) has 1-second resolution.

        Two submissions for the same PR inside one second produced the SAME id, so the
        second overwrote the first. Distinctness matters because the second is refused as
        a duplicate — but only if the first is still identifiable.
        """
        a = self.svc.enqueue_codex_review(4242)["request_id"]
        # Bypass the duplicate guard to prove id generation itself is unique.
        self.svc.PENDING_DIR.joinpath(f"{a}.json").unlink()
        b = self.svc.enqueue_codex_review(4242)["request_id"]
        self.assertNotEqual(a, b, "request_id collided within the same second")

    def test_invalid_pr_status_is_reported_not_raised(self):
        self.assertEqual(self.svc.codex_review_status("nope")["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
