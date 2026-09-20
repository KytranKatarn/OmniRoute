"""The off-site backup tier must be able to say WHY it failed (task #6804).

Both defects here were "healthy data, broken reporting": the backups really
were failing, and every channel that should have named the cause discarded it.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# sys.modules injections are PROCESS-GLOBAL: left behind, they would shadow the
# real package for every other test in the same run and turn unrelated tests
# red. Tracked here and removed in tearDownClass.
_INJECTED: list[str] = []

# A real message from backup_log, 2026-09-20: boilerplate first, cause last.
REAL_MSG = (
    "Work Suite Drive creds unavailable, falling through: "
    "('invalid_grant: Token has been expired or revoked.', {'error': "
    "'invalid_grant', 'error_description': 'Token has been expired or revoked.'})\n"
    "Traceback (most recent call last):\n"
    '  File "/app/tools/google_work_suite/services/drive_service.py", line 562, '
    "in backup_upload_file\n"
    "    status, response = request.next_chunk()\n"
    "                       ^^^^^^^^^^^^^^^^^^^^\n"
    '  File "/usr/local/lib/python3.12/site-packages/googleapiclient/_helpers.py", '
    "line 130, in positional_wrapper\n"
    "    return wrapped(*args, **kwargs)\n"
    '  File "/usr/local/lib/python3.12/site-packages/googleapiclient/http.py", '
    "line 1000, in next_chunk\n"
    "    return self._process_response(resp, content)\n"
    '  File "/usr/local/lib/python3.12/site-packages/googleapiclient/http.py", '
    "line 1031, in _process_response\n"
    "    raise HttpError(resp, content, uri=self.uri)\n"
    "googleapiclient.errors.HttpError: <HttpError 403 storageQuotaExceeded>"
)

# The fixture must be LONGER than the old caps, or it fails to reproduce the
# defect: a first draft was short enough that msg[:500] still contained the
# exception, and the DB-truncation case — the one that actually cost 3 days of
# blindness — went undemonstrated.
assert len(REAL_MSG) > 700, "fixture too short to reproduce the 500-char loss"


def _load_tier_sync():
    spec = importlib.util.spec_from_file_location(
        "tier_sync_gdrive_under_test", REPO / "scripts" / "backup" / "tier_sync_gdrive.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_drive_service():
    """Load drive_service.py directly, bypassing its package __init__.

    The real ``services/__init__.py`` eagerly imports the whole Google SDK
    surface, which is not installed on the host. Synthesising the parent
    packages lets the test execute the REAL function body instead of skipping
    (a skipped assertion proves nothing).
    """
    pkg = "tools.google_work_suite.services"
    for name in ("tools", "tools.google_work_suite", pkg):
        if name not in sys.modules:
            parent = types.ModuleType(name)
            parent.__path__ = []
            sys.modules[name] = parent
            _INJECTED.append(name)

    api = pkg + ".google_api_service"
    if api not in sys.modules:
        stub = types.ModuleType(api)
        stub.__getattr__ = lambda _n: (lambda *a, **k: None)
        sys.modules[api] = stub
        _INJECTED.append(api)

    full = pkg + ".drive_service"
    if full not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            full,
            REPO / "platform_v2" / "tools" / "google_work_suite" / "services" / "drive_service.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        _INJECTED.append(full)
        spec.loader.exec_module(mod)
    return sys.modules[full]


class ShortErrKeepsTheCause(unittest.TestCase):
    """The pre-fix code kept msg[:500] / msg[:200] — the boilerplate half."""

    def setUp(self):
        self.short_err = _load_tier_sync()._short_err

    def test_the_exception_survives_truncation(self):
        out = self.short_err(REAL_MSG, 200)
        self.assertLessEqual(len(out), 200 + 8)
        # This is the whole point: front-truncation loses this line.
        self.assertIn("storageQuotaExceeded", out)

    def test_a_front_truncation_would_have_failed_this(self):
        # Pin the defect itself, so a regression to msg[:N] is caught. Both
        # old caps are covered: 200 went to the log, 500 to backup_log.
        self.assertNotIn("storageQuotaExceeded", REAL_MSG[:200])
        self.assertNotIn("storageQuotaExceeded", REAL_MSG[:500])

    def test_the_db_cap_keeps_the_cause(self):
        # 2000 is the cap the writer now passes to log_db.
        self.assertIn("storageQuotaExceeded", self.short_err(REAL_MSG, 2000))

    def test_short_messages_pass_through_unchanged(self):
        self.assertEqual(self.short_err("boom", 200), "boom")

    def test_none_and_empty_are_safe(self):
        self.assertEqual(self.short_err(None, 100), "")
        self.assertEqual(self.short_err("", 100), "")

    def test_tiny_limit_still_prefers_the_tail(self):
        out = self.short_err(REAL_MSG, 30)
        self.assertEqual(len(out), 30)
        self.assertTrue(REAL_MSG.endswith(out))


class _FakeService:
    def __init__(self, quota):
        self._q = quota

    def about(self):
        return self

    def get(self, fields=None):
        return self

    def execute(self):
        return {"storageQuota": self._q}


class UnknownQuotaIsNotUnlimited(unittest.TestCase):
    """A storage-less service account rendered as '0.0 MB / Unlimited, 0%'."""

    def setUp(self):
        self.quota = _load_drive_service().backup_get_storage_quota

    @classmethod
    def tearDownClass(cls):
        for name in reversed(_INJECTED):
            sys.modules.pop(name, None)
        _INJECTED.clear()

    def test_absent_limit_reads_unknown_not_unlimited(self):
        out = self.quota(_FakeService({"usage": "0"}))
        self.assertFalse(out["limit_known"])
        self.assertEqual(out["limit_formatted"], "unknown")
        self.assertNotIn("nlimited", out["limit_formatted"])

    def test_percent_used_stays_numeric_when_unknown(self):
        # backup_manager.html feeds this into a CSS width; None renders "None%".
        out = self.quota(_FakeService({"usage": "0"}))
        self.assertIsInstance(out["percent_used"], (int, float))

    def test_a_real_limit_is_reported_normally(self):
        out = self.quota(_FakeService({"usage": str(3 * 1073741824), "limit": str(15 * 1073741824)}))
        self.assertTrue(out["limit_known"])
        self.assertEqual(out["limit_formatted"], "15.0 GB")
        self.assertEqual(out["percent_used"], 20.0)


if __name__ == "__main__":
    unittest.main()
