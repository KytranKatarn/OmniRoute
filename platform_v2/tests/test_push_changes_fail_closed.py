"""Regression tests for push_changes fail-closed deletion behaviour (#6760).

PR #3439 deleted six platform_v2 files because push_changes silently staged
missing-under-REPO_PATH paths as `git rm`. The container mounts platform_v2/
at /app, not at /mnt/archie_brain/platform_v2, so every platform_v2/* path
looked "missing". These tests pin the fix:

  1. a platform_v2/* path is resolved across the /app root and staged as ADD;
  2. a path missing under every root is an ERROR (never a silent deletion),
     unless explicitly declared in `removed`;
  3. a `removed` path must also be in `files`.

git/token/rate-guard internals are mocked; only the per-file staging
decision is real.
"""

import importlib.util
import os
import shutil

import pytest


def _load_github_service():
    """Load github_service.py by file path, NOT through the tools.repair_bay package.

    Importing via the package executes tools/repair_bay/__init__.py, which registers
    every route group; that pulls in services.scan_service, whose module-level
    init_tables() opens a live Postgres connection. The runner's test gate runs with
    --network none, so collection dies with "could not translate host name
    archie_database" before a single test executes (measured 2026-09-23;
    test_repair_bay_window_manifest.py fails the same way — pre-existing files only
    clear the gate because baseline == patched shields them; a NEW file has no
    baseline, so its collection error counts as a regression).

    github_service itself is import-clean (module level = constants + a logger), so
    loading it straight from its file skips the package side effects entirely — the
    same pattern as test_code_routes.py. Its only non-stdlib import is
    services.github_rate_helper, which is also side-effect-free at module level.
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "tools", "repair_bay", "services", "github_service.py")
    spec = importlib.util.spec_from_file_location("_github_service_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gs = _load_github_service()


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Back push_changes with temp repo/clone roots and mocked git plumbing."""

    repo_root = tmp_path / "repo"
    clone_root = tmp_path / "clone"
    repo_root.mkdir()
    clone_root.mkdir()
    monkeypatch.setattr(gs, "REPO_PATH", str(repo_root))
    monkeypatch.setattr(gs, "CLONE_PATH", str(clone_root))

    calls = []
    real_add = []

    def fake_run_git(args, timeout=120):
        calls.append(list(args))
        if args and args[0] == "rev-parse":
            return True, "abc1234", ""
        return True, "", ""

    monkeypatch.setattr(gs, "_run_git_clone", fake_run_git)
    monkeypatch.setattr(gs, "_ensure_clone", lambda base="main": None)
    monkeypatch.setattr(gs, "_get_token", lambda: "test-token")
    monkeypatch.setattr(
        gs,
        "check_before_write",
        lambda token: (True, {}),
    )

    def add_mock(src, dst):
        real_add.append(dst)

    # push_changes does a local `import shutil` at call time, so patch the real
    # shutil.copy2 rather than a module attribute.
    monkeypatch.setattr(shutil, "copy2", add_mock)

    return {
        "repo": repo_root,
        "clone": clone_root,
        "calls": calls,
        "real_add": real_add,
    }


def test_platform_v2_path_adds_via_app_root_when_absent_from_repo(staged, monkeypatch):
    """The PR #3439 failure mode: platform_v2 file NOT under REPO_PATH must still ADD."""
    target = "/app/app.py"
    if not os.path.isfile(target):
        pytest.skip("no /app/app.py in this environment; mount-root fallback untestable")

    result = gs.push_changes("opencode/test", ["platform_v2/app.py"], "restore app.py")
    assert result["success"], result
    # The file was staged as an add (copied from the /app root), never a deletion.
    assert staged["real_add"], "expected the platform_v2 file to be copied into the clone"
    assert not any("rm" in c[0] for c in staged["calls"])
    assert any(c[0] == "add" for c in staged["calls"])


def test_missing_under_all_roots_refuses_instead_of_deleting(staged):
    """A file in `files` that no root can provide is an error, not a silent git rm."""
    result = gs.push_changes("opencode/test", ["docs/ghost.md"], "should refuse")
    assert not result["success"]
    assert "not found" in result["error"]
    assert "removed" in result["error"]
    assert not any(
        "rm" in c[0] for c in staged["calls"]
    ), "a missing file must never be staged as a deletion without explicit intent"


def test_explicit_removed_still_deletes(staged):
    """Declaring intent via `removed` keeps real deletions possible."""
    result = gs.push_changes(
        "opencode/test",
        ["docs/ghost.md"],
        "delete ghost",
        removed=["docs/ghost.md"],
    )
    assert result["success"], result
    assert any(c[0] == "rm" for c in staged["calls"])


def test_removed_requires_files(staged):
    """A removal path not listed in `files` is rejected loudly (contract)."""
    result = gs.push_changes(
        "opencode/test",
        ["docs/other.md"],
        "delete ghost",
        removed=["docs/ghost.md"],
    )
    assert not result["success"]
    assert "not in `files`" in result["error"]
    assert not any("rm" in c[0] for c in staged["calls"])


def test_override_wins_over_missing_source(staged):
    """content_overrides provides content without a disk root — still adds, never deletes."""
    result = gs.push_changes(
        "opencode/test",
        ["platform_v2/services/x.py"],
        "add service",
        content_overrides={"platform_v2/services/x.py": "print('hi')\n"},
    )
    assert result["success"], result
    assert (staged["clone"] / "platform_v2/services/x.py").read_text() == "print('hi')\n"
    assert any(c[0] == "add" for c in staged["calls"])
    assert not any("rm" in c[0] for c in staged["calls"])
