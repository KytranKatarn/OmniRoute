"""Guards for the always-loaded instruction context (CLAUDE.md + .claude/rules/*.md).

Claude Code loads a rule file unconditionally unless its front matter carries `paths:`. Three facts shaped these checks (2026-10):
  * `globs:` is NOT a Claude Code key - it is silently ignored, so 17 rules "scoped" with it were loaded on every session (~272k chars
    against a ~150k budget). Only `paths:` scopes a rule.
  * A path-scoped rule loads only when a MATCHING file is read/written/edited. A rule whose invariant is enforced through `ssh`, `docker`
    or `psql` (no file edit) must therefore stay unconditional, or it never loads when it is needed.
  * A rule whose `paths:` patterns ALL match no file can never load (one stale pattern among live ones is harmless).

`problems()` takes the directory so the tests below can prove it FAILS on bad input instead of only passing on the good tree.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / ".claude" / "rules"
BUDGET_CHARS = 150_000

# Invariants reached through ssh / docker / psql / compose, not through editing a module's files: these must load every session.
MUST_BE_UNCONDITIONAL = {
    "fleet.md",
    "database.md",
    "stalwart-ops.md",
    "multi-repo.md",
    "deploy-provenance.md",
    "operational-state.md",
    "outpost-vps.md",
    "session-protocol.md",
    "timezone.md",
}

pytestmark = pytest.mark.skipif(not RULES.is_dir(), reason="repo .claude/rules not present (platform_v2-only mount)")


def _front_matter(text: str) -> str | None:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else None


def _paths(fm: str | None) -> list[str] | None:
    """The `paths:` list, [] if the key is present but empty, None if there is no `paths:` key."""
    if fm is None or not re.search(r"^paths:", fm, re.M):
        return None
    return re.findall(r'^\s+-\s+"?([^"\n]+?)"?\s*$', fm.split("paths:", 1)[1], re.M)


def problems(rules_dir: Path, claude_md: Path | None, repo: Path | None = None) -> list[str]:
    out, unconditional_chars = [], 0
    for f in sorted(rules_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        fm = _front_matter(text)
        if fm and re.search(r"^globs:", fm, re.M):
            out.append(
                f"{f.name}: uses `globs:` (ignored by Claude Code; the rule loads unconditionally) - use `paths:`"
            )
        paths = _paths(fm)
        if paths is None:
            unconditional_chars += len(text)
        elif not paths:
            out.append(f"{f.name}: `paths:` is present but empty")
        elif repo is not None and not any(any(True for _ in repo.glob(p)) for p in paths):
            # one stale pattern is harmless (the rule still loads via its live ones); ALL stale means the rule can never load
            out.append(f"{f.name}: none of its paths patterns {paths!r} matches any file, so this rule can never load")
        if f.name in MUST_BE_UNCONDITIONAL and paths is not None:
            out.append(
                f"{f.name}: must stay unconditional (its invariants are enforced via ssh/docker/psql, not by editing a matching file)"
            )
    if claude_md is not None:
        unconditional_chars += len(claude_md.read_text(encoding="utf-8"))
    if unconditional_chars > BUDGET_CHARS:
        out.append(f"always-loaded context is {unconditional_chars:,} chars, over the {BUDGET_CHARS:,} budget")
    return out


def test_the_real_rules_tree_is_clean():
    assert problems(RULES, REPO / "CLAUDE.md", REPO) == []


# --- prove problems() can fail: each case is a synthetic rules dir with exactly one defect --------------------------------------------------


def _mk(tmp_path, files: dict, claude_md="x"):
    d = tmp_path / "rules"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    c = tmp_path / "CLAUDE.md"
    c.write_text(claude_md, encoding="utf-8")
    return d, c


def test_globs_key_is_reported(tmp_path):
    d, c = _mk(tmp_path, {"a.md": '---\nglobs: ["x/**"]\n---\n# a\n'})
    assert any("globs" in p for p in problems(d, c))


def test_empty_paths_is_reported(tmp_path):
    d, c = _mk(tmp_path, {"a.md": "---\npaths:\n---\n# a\n"})
    assert any("empty" in p for p in problems(d, c))


def test_a_rule_whose_every_pattern_matches_nothing_is_reported(tmp_path):
    d, c = _mk(tmp_path, {"a.md": '---\npaths:\n  - "nope/**"\n  - "gone.txt"\n---\n# a\n'})
    assert any("can never load" in p for p in problems(d, c, tmp_path))


def test_one_stale_pattern_among_live_ones_is_not_reported(tmp_path):
    (tmp_path / "real.txt").write_text("x")
    d, c = _mk(tmp_path, {"a.md": '---\npaths:\n  - "nope/**"\n  - "real.txt"\n---\n# a\n'})
    assert problems(d, c, tmp_path) == []


def test_scoping_a_must_be_unconditional_rule_is_reported(tmp_path):
    d, c = _mk(tmp_path, {"database.md": '---\npaths:\n  - "database/**"\n---\n# db\n'})
    assert any("must stay unconditional" in p for p in problems(d, c))


def test_going_over_budget_is_reported(tmp_path):
    d, c = _mk(tmp_path, {"big.md": "y" * (BUDGET_CHARS + 1)})
    assert any("over the" in p for p in problems(d, c))


def test_a_scoped_rule_does_not_count_toward_the_budget(tmp_path):
    d, c = _mk(tmp_path, {"big.md": '---\npaths:\n  - "x"\n---\n' + "y" * (BUDGET_CHARS + 1)})
    assert not any("over the" in p for p in problems(d, c))
