"""The documented way to measure model/node health must exclude admission-gate sheds.

THE DEFECT THIS PINS (#6647, measured 2026-09-08):

When the hub's in-flight admission cap is reached, the dispatcher REFUSES the dispatch
and writes a ``task_execution_log`` row with ``success=false`` that still carries
``model_used`` — with 0 tokens and no inference. **The work never reached the model.**

``.claude/rules/fleet.md`` is where a human (or an agent) is told how to judge a model or
a node, and its two checklist queries counted those rows. The result was not a rounding
error, it was a reversed conclusion:

    gemma3:12b   reported 50%   ->   94% once its 2,188 shed rows (46%!) are removed

and the file went on to recommend RETIRING the model on the strength of a "56% fleet-wide"
figure made almost entirely of refusals. Every model converges to 91-94% once sheds are
excluded; the whole reported spread was shed rate.

``services/infra_failure_filter`` already existed and already had the right patterns — it
was written for AGENT-quality judgements (#5165) after the same confusion benched healthy
agents. It was simply never applied to MODEL-quality judgements. That is the fourth
instance of this codebase's recurring shape: *a correct guard exists but is not wired at
the site that needs it* (cf. #5194, #5862, #2738). The guard cannot be wired into a
markdown file, so this test does the wiring — it fails if the doc and the module drift.

Run:  docker exec archie_platform python3 -m pytest tests/test_model_health_excludes_sheds.py -v
"""

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from services.infra_failure_filter import (  # noqa: E402
    BACKPRESSURE_ERROR_PATTERNS,
    not_backpressure_sql,
)


def _find_fleet_md() -> Path | None:
    """Walk up looking for .claude/rules/fleet.md.

    ⚠️ This MUST search rather than assume a depth. The first cut hardcoded
    `parents[2]`, which is the repo root on the host but resolves to `/` inside
    `archie_platform` — where `platform_v2` IS `/app` and `.claude/` is not mounted at
    all. Every doc assertion below silently SKIPPED, so the suite reported "1 passed,
    3 skipped" and the guard protected nothing. A test that cannot fail is worse than
    no test; that is the very failure class this file exists to catch.
    """
    for parent in (_HERE, *_HERE.parents):
        candidate = parent / ".claude" / "rules" / "fleet.md"
        if candidate.is_file():
            return candidate
    return None


_FLEET_MD = _find_fleet_md()


def _fleet_md() -> str:
    if _FLEET_MD is None:  # pragma: no cover - container has no .claude mount
        pytest.skip(
            "`.claude/rules/fleet.md` not reachable from this working copy — run this "
            "test from a repo checkout on the host, not inside archie_platform "
            "(which mounts only platform_v2). Skipping here is expected; a repo-root "
            "run is what enforces the guard."
        )
    return _FLEET_MD.read_text(encoding="utf-8")


def _checklist_queries(text: str) -> list[str]:
    """The ```sql blocks under the 'MEASURE FIRST' checklist heading.

    Scoped to that section deliberately: it is the recipe someone runs before changing a
    cap or retiring a model. Other SQL in the file may legitimately count sheds (the
    sanity companion query exists precisely to MEASURE them).
    """
    start = text.find("### 1. MEASURE FIRST")
    assert start != -1, "the 'MEASURE FIRST' checklist section is gone — did the file get restructured?"
    end = text.find("### 2.", start)
    section = text[start : end if end != -1 else len(text)]
    return re.findall(r"```sql\n(.*?)```", section, re.S)


# ── the load-bearing assertion ───────────────────────────────────────────────


def test_health_queries_exclude_admission_gate_sheds():
    """A query that judges a model/node must not count refusals it never ran.

    This is the assertion that would have stopped the reversed gemma3:12b conclusion.
    """
    queries = _checklist_queries(_fleet_md())
    assert queries, "no ```sql blocks found under the MEASURE FIRST checklist"

    # 'hub saturated' is the dispatcher's own shed string and the one that did the damage.
    offenders = [q for q in queries if "success" in q and "hub saturated" not in q]
    assert not offenders, (
        "a health query counts admission-gate sheds as model/node failures — "
        "that is how gemma3:12b read 50% when it was 94%:\n\n" + "\n---\n".join(offenders)
    )


def test_documented_patterns_match_the_code_module():
    """The doc must not carry its own drifting copy of the shed signature.

    infra_failure_filter is the source of truth (its own docstring says three sites had
    already drifted). If a pattern is added there, it belongs in the doc too.
    """
    text = _fleet_md()
    missing = [p.strip("%") for p in BACKPRESSURE_ERROR_PATTERNS if p.strip("%") not in text]
    assert not missing, (
        "fleet.md's filter is missing patterns that infra_failure_filter defines "
        f"{missing} — the doc and the module have drifted"
    )


def test_doc_points_at_the_module_as_source_of_truth():
    """A reader who needs to extend this must be sent to the code, not to this file."""
    assert "infra_failure_filter" in _fleet_md(), (
        "fleet.md no longer names infra_failure_filter — without that pointer the SQL "
        "here becomes a fourth independent copy of the patterns"
    )


# ── the NULL trap that produced an impossible number during the analysis ─────


def test_the_module_predicate_is_null_safe():
    """`NOT (error ~* '...')` is NULL on a successful row and silently drops it.

    A first cut of the #6647 analysis used the naive form and reported a success rate of
    **1587%** — impossible, which is the only reason it was caught. The module's
    `NOT (NOT success AND ...)` form keeps successful rows because the inner AND is FALSE
    before the NULL comparison is ever reached.
    """
    sql = not_backpressure_sql(success_col="t.success", error_col="t.error_message")
    assert sql.startswith("NOT (NOT t.success AND"), (
        "the predicate no longer short-circuits on success; a NULL error_message will "
        f"drop successful rows from FILTER clauses. got: {sql[:80]}"
    )
    for pattern in BACKPRESSURE_ERROR_PATTERNS:
        assert pattern in sql, f"{pattern} missing from the emitted predicate"
