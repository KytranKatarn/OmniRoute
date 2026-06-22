"""Tests for the #4372 reliability hardening: mutating-skill gating, the watchdog
chrome-kill guard, and default page timeouts."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _reset_modules():
    for mod in ("skill_runner", "session_manager"):
        sys.modules.pop(mod, None)
    yield
    for mod in ("skill_runner", "session_manager"):
        sys.modules.pop(mod, None)


class TestIsMutating:
    def test_read_only_skills_are_not_mutating(self):
        import skill_runner as sr
        for name in ("linkedin_feed", "linkedin_notifications", "linkedin_search",
                     "linkedin_post_comments", "session_probe"):
            assert sr._is_mutating(name, object()) is False, name

    def test_unknown_skill_defaults_to_mutating(self):
        import skill_runner as sr
        # Conservative default — a new/unknown write skill must NOT fall back unauthed.
        assert sr._is_mutating("linkedin_post", object()) is True
        assert sr._is_mutating("linkedin_comment_reply", object()) is True
        assert sr._is_mutating("some_brand_new_skill", object()) is True

    def test_explicit_module_flag_overrides_allowlist(self):
        import skill_runner as sr
        mod_safe = type("M", (), {"MUTATING": False})
        mod_write = type("M", (), {"MUTATING": True})
        assert sr._is_mutating("linkedin_post", mod_safe) is False      # forced read
        assert sr._is_mutating("linkedin_feed", mod_write) is True       # forced write


class TestKillAgentChromeGuard:
    def test_blank_or_none_id_never_matches_all(self):
        import skill_runner as sr
        # A blank/None/zero id would build a too-broad prefix → must short-circuit to 0
        # WITHOUT scanning /proc (otherwise it could SIGKILL unrelated chromes).
        assert sr.kill_agent_chrome("") == 0
        assert sr.kill_agent_chrome(None) == 0
        assert sr.kill_agent_chrome("not-an-int") == 0

    def test_valid_id_with_no_matching_proc_returns_zero(self):
        import skill_runner as sr
        # 999999 has no chrome bound to /profiles/999999- → 0 killed, no exception.
        assert sr.kill_agent_chrome(999999) == 0


class TestSetPageTimeouts:
    def test_applies_nav_and_action_timeout(self):
        import skill_runner as sr
        page = MagicMock()
        sr._set_page_timeouts(page)
        page.set_default_navigation_timeout.assert_called_once_with(sr._NAV_TIMEOUT_MS)
        page.set_default_timeout.assert_called_once_with(sr._NAV_TIMEOUT_MS)

    def test_swallows_exceptions(self):
        import skill_runner as sr
        page = MagicMock()
        page.set_default_navigation_timeout.side_effect = RuntimeError("boom")
        sr._set_page_timeouts(page)  # must not raise


class TestMutatingFallbackGate:
    def test_mutating_skill_does_not_fall_back_to_storage_state(self, monkeypatch):
        """When the persistent profile is unavailable, a MUTATING skill must re-raise
        (fail fast) instead of running on the possibly-unauthed storage_state path."""
        import skill_runner as sr

        monkeypatch.setattr(sr, "_profile_dir", lambda a, p: "/profiles/342-linkedin")

        def _boom(*a, **k):
            raise sr._ProfileUnavailable("lock busy")

        monkeypatch.setattr(sr, "_execute_persistent", _boom)
        fake_sm = MagicMock()
        sys.modules["session_manager"] = fake_sm

        with pytest.raises(sr._ProfileUnavailable):
            sr.execute(342, "linkedin_post", {"_platform": "linkedin", "text": "hi"})

    def test_read_only_skill_does_fall_back(self, monkeypatch):
        import skill_runner as sr

        monkeypatch.setattr(sr, "_profile_dir", lambda a, p: "/profiles/342-linkedin")

        def _boom(*a, **k):
            raise sr._ProfileUnavailable("lock busy")

        monkeypatch.setattr(sr, "_execute_persistent", _boom)
        fake_sm = MagicMock()
        fake_sm.load_session.return_value = None
        sys.modules["session_manager"] = fake_sm

        # Plain module object (NOT MagicMock) so getattr(module, "MUTATING", None)
        # returns None and the read-only allowlist governs — mirrors a real import.
        class _Mod:
            @staticmethod
            def execute(page, params):
                return {"ok": True}

        def _fake_discover():
            return {"linkedin_feed": {"module": _Mod, "platforms": ["linkedin"]}}

        monkeypatch.setattr(sr, "_discover_skills", _fake_discover)

        # storage_state path uses real sync_playwright — stub it so no browser launches.
        fake_pw_cm = MagicMock()
        fake_p = MagicMock()
        fake_pw_cm.__enter__.return_value = fake_p
        fake_page = MagicMock()
        fake_page.url = "https://www.linkedin.com/feed/"
        fake_ctx = MagicMock()
        fake_ctx.new_page.return_value = fake_page
        fake_p.chromium.launch.return_value.new_context.return_value = fake_ctx
        monkeypatch.setattr(sr, "sync_playwright", lambda: fake_pw_cm)

        result = sr.execute(342, "linkedin_feed", {"_platform": "linkedin"})
        assert result == {"ok": True}  # fell back + executed


class TestWatchdog:
    def test_deadline_fires_kill_and_labels_failure(self, monkeypatch):
        """A task that exceeds the deadline must: call kill_agent_chrome (unwedge) and
        mark the task failed with a watchdog_timeout label."""
        import time as _t
        import app as appmod

        application = appmod.create_app(testing=False)
        monkeypatch.setattr(appmod, "_apply_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr(appmod, "_TASK_DEADLINE_S", 0.3)
        monkeypatch.setattr(appmod, "_log_task_to_db", lambda *a, **k: None)

        killed = {"n": 0}
        fake_sr = MagicMock()

        def _slow_run(agent_id, skill, params):
            # Watchdog fires at 0.3s and (in prod) kills chrome → Playwright raises.
            _t.sleep(0.8)
            raise RuntimeError("Target page, context or browser has been closed")

        def _kill(agent_id):
            killed["n"] += 1
            return 1

        fake_sr.run.side_effect = _slow_run
        fake_sr.kill_agent_chrome.side_effect = _kill
        sys.modules["skill_runner"] = fake_sr

        task_id = "wd-1"
        with application._tasks_lock:
            application._tasks[task_id] = {"status": "pending"}

        appmod._execute_task(application, task_id, 342, "linkedin_post", {})

        assert killed["n"] == 1, "watchdog should have force-killed the agent's chrome"
        state = application._tasks[task_id]
        assert state["status"] == "failed"
        assert "watchdog_timeout" in state["error"]

    def test_fast_task_does_not_fire_watchdog(self, monkeypatch):
        import app as appmod

        application = appmod.create_app(testing=False)
        monkeypatch.setattr(appmod, "_apply_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr(appmod, "_TASK_DEADLINE_S", 5.0)
        monkeypatch.setattr(appmod, "_log_task_to_db", lambda *a, **k: None)

        killed = {"n": 0}
        fake_sr = MagicMock()
        fake_sr.run.return_value = {"ok": True}
        fake_sr.kill_agent_chrome.side_effect = lambda a: killed.__setitem__("n", killed["n"] + 1)
        sys.modules["skill_runner"] = fake_sr

        task_id = "wd-2"
        with application._tasks_lock:
            application._tasks[task_id] = {"status": "pending"}

        appmod._execute_task(application, task_id, 342, "linkedin_feed", {})

        assert killed["n"] == 0, "watchdog must NOT fire for a fast task"
        assert application._tasks[task_id]["status"] == "completed"
