"""Website-deploy honesty audit 2026-07-28 — the state machine and its inputs.

Both public sites had sat `deploy_pending` while live content was ~2 days stale
(new portraits 404, translations.json md5 mismatch), because:

  * nothing could ever write a "bytes actually landed" status — only
    `mark_deploy_pushed` may now write 'deployed';
  * `classify_risk` was fed DIRECTORY names ("assets/portraits/", "data/"), which
    have no suffix and so always returned 'approval_required' — a constant, not a
    classification, while the translation scanner auto-deployed the same files by
    passing real .json paths.

These pin the corrected contract.
"""

import contextlib
import datetime
import os
import time

import pytest

import services.deploy_service as ds


class TestClassifyRiskWantsRealFiles:
    def test_safe_static_files_are_auto(self):
        assert ds.classify_risk(["data/translations.json", "assets/portraits/a.jpg", "index.html"]) == "auto"

    def test_directory_entries_are_never_auto(self):
        # The exact constants the daily worker used to pass.
        assert ds.classify_risk(["assets/portraits/", "data/"]) == "approval_required"

    def test_suffixless_entry_is_treated_as_directory(self):
        assert ds.classify_risk(["data"]) == "approval_required"

    def test_code_and_secrets_still_require_approval(self):
        for risky in ["deploy.py", "docker-compose.yml", "setup.sh", ".env", "schema.sql"]:
            assert ds.classify_risk([risky]) == "approval_required", risky

    def test_one_risky_file_poisons_an_otherwise_safe_set(self):
        assert ds.classify_risk(["index.html", "data/x.json", "hack.py"]) == "approval_required"

    def test_empty_list_is_auto_but_callers_must_not_rely_on_it(self):
        # Documented: [] means "nothing measurably changed"; the worker skips
        # instead of deploying, so this can never become a silent full deploy.
        assert ds.classify_risk([]) == "auto"


class TestChangedFilesSince:
    def test_lists_only_files_newer_than_the_cutoff(self, tmp_path):
        old = tmp_path / "old.json"
        old.write_text("{}")
        old_ts = time.time() - 3600
        os.utime(old, (old_ts, old_ts))
        cutoff = datetime.datetime.fromtimestamp(time.time() - 60, datetime.timezone.utc).isoformat()
        new = tmp_path / "sub" / "new.json"
        new.parent.mkdir()
        new.write_text("{}")

        got = ds.changed_files_since(str(tmp_path), cutoff)
        assert got == [os.path.join("sub", "new.json")]

    def test_unparseable_or_missing_timestamp_returns_empty(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        assert ds.changed_files_since(str(tmp_path), None) == []
        assert ds.changed_files_since(str(tmp_path), "not-a-date") == []

    def test_missing_source_dir_is_not_fatal(self):
        assert ds.changed_files_since("/nonexistent/path/xyz", "2026-01-01T00:00:00+00:00") == []

    def test_limit_caps_the_walk(self, tmp_path):
        for i in range(12):
            (tmp_path / f"f{i}.json").write_text("{}")
        cutoff = datetime.datetime.fromtimestamp(time.time() - 60, datetime.timezone.utc).isoformat()
        assert len(ds.changed_files_since(str(tmp_path), cutoff, limit=5)) == 5

    def test_output_feeds_classify_risk_meaningfully(self, tmp_path):
        """The whole point: real paths let routine content classify 'auto'."""
        (tmp_path / "translations.json").write_text("{}")
        cutoff = datetime.datetime.fromtimestamp(time.time() - 60, datetime.timezone.utc).isoformat()
        assert ds.classify_risk(ds.changed_files_since(str(tmp_path), cutoff)) == "auto"


class _FakeCursor:
    def __init__(self, store, row=None):
        self.store = store
        self._row = row

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("SELECT"):
            return
        key, value = params
        self.store[key] = value

    def fetchone(self):
        return self._row


@pytest.fixture
def store(monkeypatch):
    written = {}
    import database

    @contextlib.contextmanager
    def fake(commit=False):
        yield None, _FakeCursor(written)

    monkeypatch.setattr(database, "get_db_cursor", fake)
    return written


class TestMarkDeployPushed:
    def test_writes_deployed_status_and_push_timestamp(self, store):
        assert ds.mark_deploy_pushed("example.com") is True
        assert store["website_deploy_last_status_example.com"] == "deployed"
        assert store["website_deploy_last_push_example.com"]

    def test_records_artifact_when_given(self, store):
        ds.mark_deploy_pushed("example.com", artifact="site.zip", file_count=42, bytes_pushed=1234)
        art = store["website_deploy_last_artifact_example.com"]
        assert "site.zip" in art and "files=42" in art and "bytes=1234" in art

    def test_no_artifact_key_when_nothing_to_record(self, store):
        ds.mark_deploy_pushed("example.com")
        assert "website_deploy_last_artifact_example.com" not in store

    def test_db_failure_is_reported_not_raised(self, monkeypatch):
        import database

        @contextlib.contextmanager
        def boom(commit=False):
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(database, "get_db_cursor", boom)
        assert ds.mark_deploy_pushed("example.com") is False


class TestLastPushIso:
    def test_returns_none_when_never_pushed(self, monkeypatch):
        import database

        @contextlib.contextmanager
        def fake(commit=False):
            yield None, _FakeCursor({}, row=None)

        monkeypatch.setattr(database, "get_db_cursor", fake)
        assert ds.last_push_iso("example.com") is None

    def test_returns_recorded_value(self, monkeypatch):
        import database

        @contextlib.contextmanager
        def fake(commit=False):
            yield None, _FakeCursor({}, row={"value": "2026-07-28T12:00:00+00:00"})

        monkeypatch.setattr(database, "get_db_cursor", fake)
        assert ds.last_push_iso("example.com") == "2026-07-28T12:00:00+00:00"
