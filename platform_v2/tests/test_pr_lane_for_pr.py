"""lane_for_pr: which AI lane opened a PR, from its head branch (all lanes share one GitHub user, so the token cannot say)."""

import importlib.util
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_review_service.py"


def _load_lane_fn():
    """Pull just the lane helpers out of the (heavy, DB-importing) service module so this test needs no DB."""
    import ast

    tree = ast.parse(SRC.read_text())
    keep = [
        n
        for n in tree.body
        if (
            isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") in ("LANE_BRANCH_PREFIXES", "LANE_UNLABELLED") for t in n.targets)
        )
        or (isinstance(n, ast.FunctionDef) and n.name == "lane_for_pr")
    ]
    assert len(keep) == 3, "lane helpers not found in pr_review_service.py"
    ns: dict = {}
    exec(
        compile(ast.Module(body=keep, type_ignores=[]), str(SRC), "exec"), ns
    )  # noqa: S102 - test-only, our own source
    return ns["lane_for_pr"]


lane_for_pr = _load_lane_fn()


def test_each_lane_prefix_maps_to_its_lane():
    assert lane_for_pr("claude/fix-env-guard") == "claude"
    assert lane_for_pr("codex/reconcile-repos") == "codex"
    assert lane_for_pr("opencode/feat-gate") == "opencode"


def test_existing_machine_producers_keep_working():
    assert lane_for_pr("engine/some-slug") == "engine"
    assert lane_for_pr("cockpit/apply-1-x") == "cockpit"
    assert lane_for_pr("auto/nightly") == "automation"
    assert lane_for_pr("dependabot/pip/x") == "dependabot"


def test_title_prefix_is_the_fallback_for_machine_prs():
    assert lane_for_pr("something-else", "[engine] add thing") == "engine"
    assert lane_for_pr("something-else", "[cockpit] x") == "cockpit"


def test_unlabelled_when_nothing_matches_or_input_is_empty():
    assert lane_for_pr("fix/old-style-name") == "unlabelled"
    assert lane_for_pr("") == "unlabelled"
    assert lane_for_pr(None) == "unlabelled"


def test_lane_must_be_a_prefix_not_a_substring():
    assert lane_for_pr("fix/claude/thing") == "unlabelled"
    assert lane_for_pr("xclaude/thing") == "unlabelled"


def test_poll_records_the_lane_in_metadata():
    src = SRC.read_text()
    assert '"lane": lane_for_pr(' in src
