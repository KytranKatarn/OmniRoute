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

import pytest

import services.agent_credential_service as acs


@pytest.fixture(autouse=True)
def _isolate_credentials_store(monkeypatch):
    """#5311: reset_agent_password now writes the REAL host credentials dir
    whenever it is reachable — an unisolated run of this suite once wrote a
    bogus agent_passwords.env onto the live hub (removed by hand). Default
    every test to NO reachable candidates; tests that exercise the store
    monkeypatch their own tmp-path candidates on top of this."""
    monkeypatch.setattr(acs, "_CREDENTIALS_FILE_CANDIDATES", ())


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
        res = acs.reset_agent_password("Claude", env_paths=(os.getenv("ARCHIE_TEST_ENV_PATH"),))
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


class TestCredentialsFileStore:
    """#5311: neither archie_platform nor archie_scheduler can see the root
    .env at all, and a single-FILE rw bind mount would break the atomic
    tmp+rename writer (a file mount pins the inode). The scheduler's EXISTING
    rw directory mount /mnt/archie_brain/credentials -> /app/credentials
    becomes the canonical store (agent_passwords.env, 0600, atomic rename —
    directory mounts survive renames); the .env writes stay best-effort."""

    def test_create_missing_file_with_0600(self, tmp_path):
        target = tmp_path / "agent_passwords.env"
        wrote = acs._rewrite_env_line(str(target), "ARCHIE_CLAUDE_PASSWORD", "s3cret!A9x", create=True)
        assert wrote is True
        assert target.read_text() == "ARCHIE_CLAUDE_PASSWORD=s3cret!A9x\n"
        assert (os.stat(target).st_mode & 0o777) == 0o600

    def test_without_create_missing_file_still_skipped(self, tmp_path):
        target = tmp_path / "nope.env"
        assert acs._rewrite_env_line(str(target), "K", "v") is False
        assert not target.exists()

    def test_write_credentials_file_picks_first_existing_parent(self, tmp_path, monkeypatch):
        good = tmp_path / "credentials"
        good.mkdir()
        monkeypatch.setattr(
            acs,
            "_CREDENTIALS_FILE_CANDIDATES",
            (str(tmp_path / "missing" / "agent_passwords.env"), str(good / "agent_passwords.env")),
        )
        path = acs._write_credentials_file("ARCHIE_ARCHIE_PASSWORD", "pw!A9x")
        assert path == str(good / "agent_passwords.env")
        assert "ARCHIE_ARCHIE_PASSWORD=pw!A9x" in (good / "agent_passwords.env").read_text()

    def test_write_credentials_file_none_when_no_parent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            acs,
            "_CREDENTIALS_FILE_CANDIDATES",
            (str(tmp_path / "a" / "x.env"), str(tmp_path / "b" / "x.env")),
        )
        assert acs._write_credentials_file("K", "v") is None

    def test_root_write_aligns_ownership_with_parent_dir(self, tmp_path, monkeypatch):
        """#5311 live-probe finding (2026-07-27): both containers run as ROOT, so
        the store landed root:root 0600 — unreadable by the host-side owner the
        file exists for (the login skill runs as kytran). When euid==0 the writer
        must chown the file to the credentials DIR's owner."""
        good = tmp_path / "credentials"
        good.mkdir()
        target = str(good / "agent_passwords.env")
        monkeypatch.setattr(acs, "_CREDENTIALS_FILE_CANDIDATES", (target,))
        chowns = []
        monkeypatch.setattr(acs.os, "geteuid", lambda: 0)
        monkeypatch.setattr(acs.os, "chown", lambda p, uid, gid: chowns.append((p, uid, gid)))
        assert acs._write_credentials_file("K", "v") == target
        parent = os.stat(str(good))
        assert chowns == [(target, parent.st_uid, parent.st_gid)]

    def test_nonroot_write_skips_chown(self, tmp_path, monkeypatch):
        good = tmp_path / "credentials"
        good.mkdir()
        target = str(good / "agent_passwords.env")
        monkeypatch.setattr(acs, "_CREDENTIALS_FILE_CANDIDATES", (target,))
        chowns = []
        monkeypatch.setattr(acs.os, "geteuid", lambda: 4242)
        monkeypatch.setattr(acs.os, "chown", lambda p, uid, gid: chowns.append((p, uid, gid)))
        assert acs._write_credentials_file("K", "v") == target
        assert chowns == []  # non-root cannot (and must not try to) chown

    def test_reset_writes_credentials_file_first_and_reports_it(self, tmp_path, monkeypatch):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        cred_dir = tmp_path / "credentials"
        cred_dir.mkdir()
        cred_file = cred_dir / "agent_passwords.env"
        monkeypatch.setattr(acs, "_CREDENTIALS_FILE_CANDIDATES", (str(cred_file),))
        res = acs.reset_agent_password("claude", env_paths=())
        assert res["success"] is True
        assert res["credentials_file"] == str(cred_file)
        assert str(cred_file) in res["env_written"]
        content = cred_file.read_text()
        assert content.startswith("ARCHIE_CLAUDE_PASSWORD=")
        secret = content.split("=", 1)[1].strip()
        assert secret and secret not in str(res)  # result stays secret-free


class TestSkippedEnvStoresAreReported:
    """A store that could NOT be written must never look like one that was not configured.

    Measured 2026-09-20: rotating `claude` from inside archie_scheduler returned
    env_written=['/app/credentials/agent_passwords.env', '/app/.env'] and root
    .env — the file docker-compose actually gives the platform via `env_file:` —
    silently kept its Sep-13 value, because it is not mounted there and
    _rewrite_env_line(create=False) returns False for a missing file. The DB and
    the canonical store were correct; the DEPLOYED env var was stale and nothing
    said so. These keys did not exist before the fix, so each assertion below
    fails against the old module.
    """

    def test_a_missing_env_path_is_REPORTED_not_silently_dropped(self, monkeypatch, tmp_path):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        missing = str(tmp_path / "nope" / ".env")
        res = acs.reset_agent_password("claude", env_paths=(missing,))
        assert res["success"] is True
        assert "env_skipped" in res, "a skip must be reported, not dropped"
        assert [e["path"] for e in res["env_skipped"]] == [missing]
        assert missing not in res["env_written"]

    def test_a_skipped_RUNTIME_env_file_raises_a_warning(self, monkeypatch, tmp_path):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        missing = str(tmp_path / "gone" / ".env")
        monkeypatch.setattr(acs, "_RUNTIME_ENV_FILES", frozenset({missing}))
        res = acs.reset_agent_password("claude", env_paths=(missing,))
        assert res["warning"], "a stale RUNTIME env store is the one case a caller must act on"
        assert missing in res["warning"]
        # The warning must say how to APPLY it: a restart does not re-read env_file.
        assert "up -d" in res["warning"]
        assert res["warning"].count("password") >= 1

    def test_a_written_path_is_not_reported_skipped(self, monkeypatch, tmp_path):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        env = tmp_path / ".env"
        env.write_text("UNRELATED=keep\n")
        monkeypatch.setattr(acs, "_RUNTIME_ENV_FILES", frozenset({str(env)}))
        res = acs.reset_agent_password("claude", env_paths=(str(env),))
        assert str(env) in res["env_written"]
        assert res["env_skipped"] == []
        assert res["warning"] is None, "a store that WAS written must not warn"
        assert "UNRELATED=keep" in env.read_text(), "rotation must not clobber other secrets"

    def test_a_skipped_NON_runtime_path_does_not_warn(self, monkeypatch, tmp_path):
        db = _RecordingDB()
        monkeypatch.setattr(acs, "get_db_cursor", db)
        missing = str(tmp_path / "absent" / ".env")
        monkeypatch.setattr(acs, "_RUNTIME_ENV_FILES", frozenset({"/some/other/.env"}))
        res = acs.reset_agent_password("claude", env_paths=(missing,))
        assert res["env_skipped"], "still reported"
        assert res["warning"] is None, "only a RUNTIME-loaded store is worth a warning"

    def test_the_default_paths_include_the_file_the_runtime_loads(self):
        # Pins the pairing. If someone drops root .env from _DEFAULT_ENV_PATHS the
        # warning can never fire, and the silent-skip bug returns wearing a hat.
        assert "/mnt/archie_brain/.env" in acs._DEFAULT_ENV_PATHS
        assert acs._RUNTIME_ENV_FILES <= set(acs._DEFAULT_ENV_PATHS)
