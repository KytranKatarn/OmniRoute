"""#5303 — agent-account password rotation: scoped, approval-gated, secret-free bookkeeping.

Pins the safety properties of services/agent_credential_service.py:
  * HARD SCOPE: only 'claude'/'archie' are resettable — kytran, admin, and every human
    account are refused BEFORE any DB or file touch (the 2026-05-08 lockout class).
  * Generated passwords always satisfy validate_password_complexity.
  * The env rewrite is atomic, replaces-in-place or appends, and preserves file mode.
  * The result dict NEVER contains the password (approval-queue results are logged).
  * A missing env store does not undo the DB rotation (DB hash is authoritative).
"""

import os
import re
from contextlib import contextmanager

import services.agent_credential_service as acs


class _RecordingDB:
    def __init__(self, returning_row={"id": 59}):
        self.executed = []
        self.row = returning_row

    @contextmanager
    def __call__(self, *a, **k):
        db = self

        class _Cur:
            def execute(self, sql, params=None):
                db.executed.append((sql, params))

            def fetchone(self):
                return db.row

        yield None, _Cur()


class TestScope:
    def test_refuses_every_non_agent_account_before_any_touch(self, monkeypatch):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        for name in ("kytran", "admin", "KYTRAN", "root", "", None, "claude2"):
            res = acs.reset_agent_password(name, env_paths=())
            assert res["success"] is False, name
            assert "refused" in res["error"] or "not an agent" in res["error"]
        assert db.executed == [], "a refused username must never reach the DB"

    def test_agent_accounts_accepted_case_insensitively(self, monkeypatch):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        res = acs.reset_agent_password("Claude", env_paths=())
        assert res["success"] is True
        assert res["username"] == "claude"


class TestPasswordProperties:
    def test_generated_password_meets_platform_complexity(self):
        from services.auth_service import validate_password_complexity

        for _ in range(20):
            pw = acs.generate_agent_password()
            ok, _msg = (
                validate_password_complexity(pw)
                if isinstance(validate_password_complexity(pw), tuple)
                else (validate_password_complexity(pw), "")
            )
            assert ok, pw

    def test_result_never_contains_the_password(self, monkeypatch, tmp_path):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        env = tmp_path / ".env"
        env.write_text("OTHER=1\n")
        captured = {}
        real_gen = acs.generate_agent_password

        def spy():
            captured["pw"] = real_gen()
            return captured["pw"]

        monkeypatch.setattr(acs, "generate_agent_password", spy)
        res = acs.reset_agent_password("claude", env_paths=(str(env),))
        assert res["success"] is True
        blob = repr(res)
        assert captured["pw"] not in blob, "password leaked into the bookkeeping result"
        assert captured["pw"] in env.read_text(), "password must land in the env store"


class TestEnvRewrite:
    def test_replaces_existing_line_in_place(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nARCHIE_CLAUDE_PASSWORD=oldvalue\nB=2\n")
        assert acs._rewrite_env_line(str(env), "ARCHIE_CLAUDE_PASSWORD", "newvalue") is True
        text = env.read_text()
        assert "ARCHIE_CLAUDE_PASSWORD=newvalue\n" in text
        assert "oldvalue" not in text
        assert text.startswith("A=1\n") and text.endswith("B=2\n"), "neighbors must be untouched"

    def test_appends_when_key_absent_and_preserves_mode(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1")
        os.chmod(env, 0o600)
        assert acs._rewrite_env_line(str(env), "ARCHIE_ARCHIE_PASSWORD", "v") is True
        assert env.read_text() == "A=1\nARCHIE_ARCHIE_PASSWORD=v\n"
        assert (os.stat(env).st_mode & 0o777) == 0o600

    def test_missing_file_is_skipped_not_fatal(self, tmp_path, monkeypatch):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        res = acs.reset_agent_password("claude", env_paths=(str(tmp_path / "nope.env"),))
        assert res["success"] is True
        assert res["env_written"] == []


class TestDbSemantics:
    def test_rotation_clears_failed_login_count_and_targets_active_user(self, monkeypatch):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        acs.reset_agent_password("archie", env_paths=())
        sql = db.executed[0][0]
        assert "failed_login_count = 0" in sql
        assert "is_active = true" in sql
        assert db.executed[0][1][1] == "archie"
        assert re.search(r"password_hash\s*=\s*%s", sql)

    def test_inactive_or_missing_user_reports_failure(self, monkeypatch):
        db = _RecordingDB(returning_row=None)
        monkeypatch.setattr(acs, "get_db_cursor", db)
        res = acs.reset_agent_password("claude", env_paths=())
        assert res["success"] is False
        assert "not found or inactive" in res["error"]
