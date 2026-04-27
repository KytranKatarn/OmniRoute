import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet as _Fernet
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "")


class TestSkillDiscovery:
    def test_discover_returns_dict(self, tmp_path, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        skill_file = tmp_path / "fake_skill.py"
        skill_file.write_text('SKILL_NAME="fake_skill"\nPLATFORMS=["test"]\ndef execute(page, params): return {"done": True}')
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
