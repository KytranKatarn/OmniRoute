"""Canonical fact-check verdict vocabulary — ONE definition, every writer.

TWO columns, TWO vocabularies, and conflating them is the whole reason this file
exists:

  fact_checks.verdict          PER-CLAIM   true | mostly_true | mixed | false | unverified
                               (CHECK constraint `fact_verdict_check`, enforced)

  fact_checks.overall_verdict  PER-ARTICLE verified | mostly_true | mixed | disputed |
                               unverifiable | descriptive_reporting
                               (was UNCONSTRAINED until migration 060)

`unverified` and `unverifiable` are NOT synonyms for the same column — the first
is per-claim vocabulary, the second per-article. 32,919 rows carried `unverified`
in overall_verdict because the two got mixed.

WHY THIS MODULE EXISTS
`llm_analysis_backlog_worker` already had a correct _OVERALL_VERDICT_MAP, but
ingest/run.py:253 wrote `verify_result.get("overall_verdict")` RAW — the model's
free text straight into an unconstrained column. Measured 2026-08-31 that produced
`factual_reporting` (9), `most_factual` (3) and `verified_facts` (21) alongside the
real values, all `analyzed_by='VERIFY_LLM'`.

One vocabulary with two implementations, one of which was missing entirely. Same
shape as `queued_dispatch_text` and the `node_has_model` guard: the fix is a single
definition every writer calls, not a second copy.

FAIL-CLOSED: an unrecognised label maps to the honest "cannot say" value for that
column rather than passing through. A verdict the schema does not know is worse
than no verdict — it renders on a public accountability page.
"""

from typing import Optional

# ── per-article (overall_verdict) ────────────────────────────────────────────
OVERALL_VERDICTS = frozenset(
    {
        "verified",
        "mostly_true",
        "mixed",
        "disputed",
        "unverifiable",
        "descriptive_reporting",
    }
)

_OVERALL_ALIASES = {
    # per-claim vocabulary leaking into the per-article column
    "unverified": "unverifiable",
    "true": "verified",
    "false": "disputed",
    "mostly_false": "disputed",
    # free-text the model invented outside the rubric (measured 2026-08-31)
    "verified_facts": "verified",
    "most_factual": "mostly_true",
    # "factual reporting" describes the ARTICLE's character, not a verification
    # outcome — that is exactly what descriptive_reporting means.
    "factual_reporting": "descriptive_reporting",
    "descriptive": "descriptive_reporting",
    "no_claims": "descriptive_reporting",
}

# ── per-claim (verdict) ──────────────────────────────────────────────────────
CLAIM_VERDICTS = frozenset({"true", "mostly_true", "mixed", "false", "unverified"})

_CLAIM_ALIASES = {
    "verified": "true",
    "unverifiable": "unverified",
    "disputed": "mixed",
    "mostly_false": "false",
    # a per-article label arriving on a claim: the claim itself is not adjudicated
    "descriptive_reporting": "unverified",
}


def _norm(value) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def canonical_overall(value) -> Optional[str]:
    """Model output -> a valid overall_verdict, or None.

    None (not a guess) when the label is unrecognised: overall_verdict is
    NULLable, and an honest absence beats inventing an adjudication.
    """
    v = _norm(value)
    if not v:
        return None
    if v in OVERALL_VERDICTS:
        return v
    return _OVERALL_ALIASES.get(v)


def canonical_claim(value) -> str:
    """Model output -> a valid per-claim verdict.

    NOT nullable — the column is NOT NULL-ish in practice and CHECK-constrained,
    so an unknown label becomes `unverified`, which is the truthful "we did not
    establish this" rather than a fabricated verdict.
    """
    v = _norm(value)
    if v in CLAIM_VERDICTS:
        return v
    return _CLAIM_ALIASES.get(v, "unverified")
