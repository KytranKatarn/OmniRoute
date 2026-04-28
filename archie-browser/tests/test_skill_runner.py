import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet as _Fernet
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _reset_skill_runner_module():
    """Evict any MagicMock injected into sys.modules by create_app(testing=True)
    so tests always get the real skill_runner module."""
    for mod in ("skill_runner", "session_manager"):
        sys.modules.pop(mod, None)
    yield
    for mod in ("skill_runner", "session_manager"):
        sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# Pre-existing tests (kept intact)
# ---------------------------------------------------------------------------

class TestSkillDiscovery:
    def test_discover_returns_dict(self, tmp_path, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        skill_file = tmp_path / "fake_skill.py"
        skill_file.write_text(
            'SKILL_NAME="fake_skill"\nPLATFORMS=["test"]\ndef execute(page, params): return {"done": True}'
        )
        skills = skill_runner._discover_skills()
        assert "fake_skill" in skills

    def test_discover_skips_init(self, tmp_path, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        (tmp_path / "__init__.py").write_text("")
        skills = skill_runner._discover_skills()
        assert "__init__" not in skills

    def test_unknown_skill_raises(self, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "_discover_skills", lambda: {})
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_runner.run(agent_id=1, skill_name="nonexistent", params={})


# ---------------------------------------------------------------------------
# Task 3 — new tests
# ---------------------------------------------------------------------------

class TestTask3SkillRunner:
    def test_discover_skills(self, tmp_path, monkeypatch):
        """Temp skill file is discovered with correct platforms."""
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        skill_file = tmp_path / "my_skill.py"
        skill_file.write_text(
            'SKILL_NAME="my_skill"\nPLATFORMS=["linkedin","twitter"]\n'
            'def execute(page, params): return {"ok": True}'
        )
        skills = skill_runner._discover_skills()
        assert "my_skill" in skills
        assert skills["my_skill"]["platforms"] == ["linkedin", "twitter"]

    def test_list_skills(self, monkeypatch):
        """list_skills() returns [{name, platforms}] for each skill."""
        import skill_runner

        fake_skills = {
            "skill_a": {"module": None, "platforms": ["linkedin"]},
            "skill_b": {"module": None, "platforms": ["twitter", "facebook"]},
        }
        monkeypatch.setattr(skill_runner, "_discover_skills", lambda: fake_skills)

        result = skill_runner.list_skills()
        names = {s["name"] for s in result}
        assert names == {"skill_a", "skill_b"}
        by_name = {s["name"]: s for s in result}
        assert by_name["skill_a"]["platforms"] == ["linkedin"]
        assert by_name["skill_b"]["platforms"] == ["twitter", "facebook"]

    def test_execute_unknown_skill(self, monkeypatch):
        """execute() raises ValueError when skill_name is not found."""
        import skill_runner
        monkeypatch.setattr(skill_runner, "_discover_skills", lambda: {})
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_runner.execute(1, "nonexistent", {})

    def test_login_no_credentials(self, monkeypatch):
        """login() raises ValueError when get_credentials returns None."""
        import skill_runner
        import session_manager

        monkeypatch.setattr(session_manager, "get_credentials", lambda agent_id, platform: None)

        with pytest.raises(ValueError):
            skill_runner.login(1, "linkedin")


# ---------------------------------------------------------------------------
# Fix 4 — mock-based Playwright path tests
# ---------------------------------------------------------------------------

class TestExecutePlaywrightPaths:
    def _make_pw_mock(self, mock_browser):
        """Return a sync_playwright context manager mock wired to mock_browser."""
        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw = MagicMock()
        mock_pw.__enter__ = lambda s: mock_pw_instance
        mock_pw.__exit__ = MagicMock(return_value=False)
        return mock_pw

    def test_execute_success_saves_session(self, monkeypatch):
        import types
        import skill_runner as sr

        fake_skill_mod = types.ModuleType("fake_skill")
        fake_skill_mod.SKILL_NAME = "fake_skill"
        fake_skill_mod.PLATFORMS = ["linkedin"]
        fake_skill_mod.execute = lambda page, params: {"success": True, "result": "ok"}
        monkeypatch.setattr(
            sr,
            "_discover_skills",
            lambda: {"fake_skill": {"module": fake_skill_mod, "platforms": ["linkedin"]}},
        )

        mock_sm = MagicMock()
        mock_sm.load_session.return_value = None
        mock_sm.save_session.return_value = None
        monkeypatch.setitem(sys.modules, "session_manager", mock_sm)

        mock_context = MagicMock()
        mock_context.storage_state.return_value = {}
        mock_context.new_page.return_value = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        with patch("skill_runner.sync_playwright", return_value=self._make_pw_mock(mock_browser)):
            result = sr.execute(1, "fake_skill", {})

        assert result["success"] is True
        mock_sm.save_session.assert_called_once_with(1, "linkedin", {})

    def test_execute_failure_marks_error(self, monkeypatch):
        import types
        import skill_runner as sr

        fake_skill_mod = types.ModuleType("failing_skill")
        fake_skill_mod.SKILL_NAME = "failing_skill"
        fake_skill_mod.PLATFORMS = ["twitter"]

        def _raise(page, params):
            raise RuntimeError("boom")

        fake_skill_mod.execute = _raise
        monkeypatch.setattr(
            sr,
            "_discover_skills",
            lambda: {"failing_skill": {"module": fake_skill_mod, "platforms": ["twitter"]}},
        )

        mock_sm = MagicMock()
        mock_sm.load_session.return_value = None
        monkeypatch.setitem(sys.modules, "session_manager", mock_sm)

        mock_context = MagicMock()
        mock_context.new_page.return_value = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        with patch("skill_runner.sync_playwright", return_value=self._make_pw_mock(mock_browser)):
            with pytest.raises(RuntimeError, match="boom"):
                sr.execute(1, "failing_skill", {})

        mock_sm.mark_error.assert_called_once_with(1, "twitter", "boom")
        mock_context.close.assert_called_once()
