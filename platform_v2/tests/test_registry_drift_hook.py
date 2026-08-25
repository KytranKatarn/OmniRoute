"""The registry-drift gate must be SATISFIABLE, not just strict (#5602).

A gate that cannot pass is worse than no gate: every author learns to reach for
SKIP_REGISTRY_DRIFT=1, and the reflex carries over to the commits where the gate
would have caught something real. That is exactly what #5230 exists to prevent —
its predecessor left backups unmonitored while appearing monitored.

THE BUG: .pre-commit-config.yaml runs this hook with `pass_filenames: true` and a
`files:` regex that selects registry SOURCES. Neither generated doc can match
that regex (it allows `.claude/skills|commands/`, not `.claude/rules/`), so the
doc never appears in argv and `_DOC not in files` was ALWAYS true. Regenerating
the doc correctly still failed the hook. Hit live on PR #2577.

These tests pin BOTH halves: the gate must pass when the doc IS staged, and must
still fail when it is not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from tests.repo_root import repo_root


def _find_hook() -> Path:
    """Locate the hook from either layout.

    On the host this file is /mnt/archie_brain/platform_v2/tests/...; inside
    archie_platform, platform_v2 is bind-mounted at /app, so parents[2] is "/"
    and the repo-relative guess misses. Try both rather than assume.
    """
    candidates = [
        repo_root() / "scripts" / "check_registry_drift.py",
        Path("/mnt/archie_brain/scripts/check_registry_drift.py"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise AssertionError(f"check_registry_drift.py not found in any of: {candidates}")


_HOOK = _find_hook()


def _load(path: Path = _HOOK):
    """Import the hook by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location(f"_drift_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _no_skip(monkeypatch):
    """SKIP_REGISTRY_DRIFT in the ambient env would make every test vacuously pass."""
    monkeypatch.delenv("SKIP_REGISTRY_DRIFT", raising=False)


def _run(mod, argv_files, staged, monkeypatch):
    """Invoke main() the way pre-commit does: argv = SOURCES only."""
    monkeypatch.setattr(mod, "_staged", lambda: list(staged))
    return mod.main(["check_registry_drift.py", *argv_files])


# --- the regression: doc regenerated, but pre-commit only passed the source ---


def test_service_doc_staged_passes_even_though_argv_has_only_the_source(monkeypatch):
    """THE #5602 REGRESSION. argv=[source] (all pre-commit can pass) + doc staged => allowed."""
    mod = _load()
    rc = _run(
        mod,
        argv_files=["docker-compose.yml"],
        staged=["docker-compose.yml", mod._SERVICE_DOC],
        monkeypatch=monkeypatch,
    )
    assert rc == 0, "doc WAS regenerated and staged — the gate must be satisfiable"


def test_module_doc_staged_passes_even_though_argv_has_only_the_source(monkeypatch):
    """Same defect on the module half — module-capability-index.md also can't match the regex."""
    mod = _load()
    rc = _run(
        mod,
        argv_files=["platform_v2/module_registry.py"],
        staged=["platform_v2/module_registry.py", mod._MODULE_DOC],
        monkeypatch=monkeypatch,
    )
    assert rc == 0, "doc WAS regenerated and staged — the gate must be satisfiable"


# --- the gate must still bite: these guard against "fixing" it into a no-op ---


def test_service_source_without_doc_still_fails(monkeypatch):
    mod = _load()
    rc = _run(mod, argv_files=["docker-compose.yml"], staged=["docker-compose.yml"], monkeypatch=monkeypatch)
    assert rc == 1, "source changed, doc NOT regenerated — the gate must still fail"


def test_module_source_without_doc_still_fails(monkeypatch):
    mod = _load()
    rc = _run(
        mod,
        argv_files=["platform_v2/module_registry.py"],
        staged=["platform_v2/module_registry.py"],
        monkeypatch=monkeypatch,
    )
    assert rc == 1, "source changed, doc NOT regenerated — the gate must still fail"


def test_unrelated_change_passes(monkeypatch):
    mod = _load()
    rc = _run(mod, argv_files=["README.md"], staged=["README.md"], monkeypatch=monkeypatch)
    assert rc == 0


def test_skill_change_alone_does_not_gate(monkeypatch):
    """Deliberate per the hook's own comment: skills have no doc renderer yet."""
    mod = _load()
    rc = _run(
        mod,
        argv_files=[".claude/skills/foo/SKILL.md"],
        staged=[".claude/skills/foo/SKILL.md"],
        monkeypatch=monkeypatch,
    )
    assert rc == 0


def test_skip_env_still_escapes(monkeypatch):
    mod = _load()
    monkeypatch.setenv("SKIP_REGISTRY_DRIFT", "1")
    rc = _run(mod, argv_files=["docker-compose.yml"], staged=["docker-compose.yml"], monkeypatch=monkeypatch)
    assert rc == 0


def test_no_files_at_all_passes(monkeypatch):
    mod = _load()
    rc = _run(mod, argv_files=[], staged=[], monkeypatch=monkeypatch)
    assert rc == 0


# --- proof the suite CANNOT pass against the defect (repair-bay.md rule) ---


def test_suite_detects_the_original_defect(tmp_path, monkeypatch):
    """A test that cannot fail is worse than no test.

    Rebuild the pre-fix logic in a COPY (never mutate the live file) and assert
    the satisfiable-gate tests fail against it. If this ever passes, the fix has
    been reverted or the tests have gone vacuous.
    """
    src = _HOOK.read_text()
    broken = src.replace("regenerated = set(files) | set(staged)", "regenerated = set(files)")
    assert broken != src, "fix marker not found — update this test alongside the hook"

    copy = tmp_path / "check_registry_drift_broken.py"
    copy.write_text(broken)
    mod = _load(copy)

    rc = _run(
        mod,
        argv_files=["docker-compose.yml"],
        staged=["docker-compose.yml", mod._SERVICE_DOC],
        monkeypatch=monkeypatch,
    )
    assert rc == 1, "the defect must reproduce in the copy — otherwise these tests prove nothing"
