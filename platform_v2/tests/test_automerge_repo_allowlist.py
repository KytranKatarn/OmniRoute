"""Auto-merge repo allowlist (#4494 widened 2026-08-29, decision #1049 follow-on).

Owner decision: KSO (kytran-system-operations) is software managed and created on
this platform, so it auto-merges under the SAME safety gates as archie-platform.
These tests pin the three properties that make that widening safe:

  * the repo allowlist is deny-by-default — watch repos and KBS stay review-only
    (the write token measurably has no access there, #5981);
  * per-repo path allowlists — KSO auto-merges only docs and tests, never service
    code / compose / Dockerfile / rule_packs; and
  * a repo added to FORGE_AUTOMERGE_REPOS without a path-allowlist entry still
    blocks on paths — two independent deny-by-default layers.
"""

from unittest.mock import patch

from tools.repair_bay.services import pr_review_service as prs

_KSO = "KytranKatarn/kytran-system-operations"
_PLATFORM = "KytranKatarn/archie-platform"
_WATCH = "KytranKatarn/kytran-gov-watch"


def _files(*names):
    """Shape of the GitHub /pulls/N/files payload the allowlist reads."""
    return True, [{"filename": n} for n in names]


class TestAutomergeRepos:
    def test_default_contains_platform_and_kso(self):
        repos = prs.automerge_repos()
        assert _PLATFORM in repos
        assert _KSO in repos

    def test_watch_repos_and_kbs_are_not_automerge(self):
        repos = prs.automerge_repos()
        assert _WATCH not in repos
        assert "KytranKatarn/kytran-business-suite" not in repos

    def test_env_override_replaces_the_default(self, monkeypatch):
        monkeypatch.setenv("FORGE_AUTOMERGE_REPOS", "KytranKatarn/archie-platform")
        repos = prs.automerge_repos()
        assert repos == ("KytranKatarn/archie-platform",)
        assert _KSO not in repos


class TestPerRepoPathAllowlist:
    def test_kso_docs_and_tests_are_allowed(self):
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files(
                "README.md", "docs/setup.md", "kytran_system_operations/test_gpu_info.py", "tests/test_x.py"
            ),
        ):
            ok, blocking = prs._automerge_paths_allowed(1, _KSO)
        assert ok, f"docs/tests should auto-merge in KSO, blocked: {blocking}"

    def test_kso_service_code_blocks(self):
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("kytran_system_operations/app.py", "README.md"),
        ):
            ok, blocking = prs._automerge_paths_allowed(2, _KSO)
        assert not ok
        assert "kytran_system_operations/app.py" in blocking

    def test_kso_compose_dockerfile_and_rulepacks_block(self):
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("docker-compose.yml", "Dockerfile", "rule_packs/hipaa.json"),
        ):
            ok, blocking = prs._automerge_paths_allowed(3, _KSO)
        assert not ok
        assert set(blocking) == {"docker-compose.yml", "Dockerfile", "rule_packs/hipaa.json"}

    def test_unlisted_repo_blocks_everything_even_docs(self):
        """Layer 2 of deny-by-default: a repo in FORGE_AUTOMERGE_REPOS but absent
        from _SAFE_AUTOMERGE_PATTERNS_BY_REPO must still block every file."""
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("README.md"),
        ):
            ok, blocking = prs._automerge_paths_allowed(4, _WATCH)
        assert not ok
        assert blocking == ["<no auto-merge path allowlist for this repo>"]

    def test_default_repo_behavior_unchanged(self):
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("platform_v2/tests/test_x.py", "docs/a.md"),
        ):
            ok, _ = prs._automerge_paths_allowed(5, _PLATFORM)
        assert ok
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("platform_v2/services/agent_service.py"),
        ):
            ok, blocking = prs._automerge_paths_allowed(6, _PLATFORM)
        assert not ok and "platform_v2/services/agent_service.py" in blocking

    def test_safe_paths_env_override_applies_to_default_repo_only(self, monkeypatch):
        """FORGE_AUTOMERGE_SAFE_PATHS keeps its historical contract: it replaces the
        DEFAULT repo's patterns and must not silently widen (or narrow) KSO's."""
        monkeypatch.setenv("FORGE_AUTOMERGE_SAFE_PATHS", r"^kytran_system_operations/")
        with patch(
            "tools.repair_bay.services.github_service._api_get",
            return_value=_files("kytran_system_operations/app.py"),
        ):
            ok_kso, _ = prs._automerge_paths_allowed(7, _KSO)
            ok_default, _ = prs._automerge_paths_allowed(8, _PLATFORM)
        assert not ok_kso, "the env override must not widen KSO's allowlist"
        assert ok_default, "the env override still governs the default repo"
