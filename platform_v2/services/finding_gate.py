"""Auto-verify trust gate for static-analysis findings (Code Health static tier).

Encodes the 2026-07-11 session's triage discipline:
  - Deterministic tools/codes (AST sweeps, pyflakes F821, ruff F-codes) are
    near-zero false-positive -> auto-CONFIRMED, zero LLM cost.
  - Judgment findings (bandit, mypy, pylint) are adversarially verified THROUGH
    the DHQ dispatcher: the owning agent must NAME the concrete failure or the
    finding stays advisory.
  - FAIL-CLOSED: a verify error, an unsuccessful dispatch, or an exhausted
    verify budget leaves the finding advisory — never auto-confirmed.

Spec: docs/superpowers/specs/2026-07-11-code-health-static-analysis-scanner-tier-design.md §4.2
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Near-zero false-positive tools/codes -> auto-confirm (no dispatch).
_DETERMINISTIC_TOOLS = {"ast_sweep", "pyflakes", "ruff"}
_DETERMINISTIC_CODES = {
    "F821",
    "WRONG_ROOT_IMPORT",
    "WRONG_SUBMODULE_IMPORT",
    "MISSING_SYMBOL",
    "WRONG_KWARG",
    "ARITY_MISMATCH",
    "SYNTAX_ERROR",
}

# Bounded per gate run: the first whole-tree scan can emit hundreds of judgment
# findings, and each verify is a fleet dispatch. Overflow stays advisory and is
# picked up by a later run once the backlog drains (dedup keeps it cheap).
DEFAULT_MAX_VERIFICATIONS = 25

_VERIFY_SYSTEM = (
    "You are adversarially verifying a static-analysis finding. Decide if it is "
    "a REAL runtime bug. Default to FALSE-POSITIVE unless you can name the "
    "concrete failure (inputs -> wrong output/crash). Reply starting with "
    "exactly 'CONFIRMED:' or 'FALSE-POSITIVE:' followed by one sentence."
)


def _is_deterministic(finding: dict) -> bool:
    return finding.get("tool") in _DETERMINISTIC_TOOLS or finding.get("code") in _DETERMINISTIC_CODES


def _default_dispatcher(capability, prompt, module_id="finding_gate", system_prompt=None):
    from tools.department_hq.services.department_dispatcher import dispatch

    return dispatch(capability=capability, prompt=prompt, module_id=module_id, system_prompt=system_prompt)


def _verify(finding: dict, dispatcher) -> bool:
    prompt = (
        f"Finding from {finding.get('tool')} [{finding.get('code')}] "
        f"at {finding.get('file')}:{finding.get('line')}\n"
        f"{finding.get('message') or finding.get('detail', '')}\n\n"
        "Is this a real runtime bug? Prove it or reject it."
    )
    try:
        result = dispatcher(
            capability=finding.get("capability", "code"),
            prompt=prompt,
            module_id="finding_gate",
            system_prompt=_VERIFY_SYSTEM,
        )
        if not getattr(result, "success", False):
            return False
        return (getattr(result, "response", "") or "").strip().upper().startswith("CONFIRMED")
    except Exception as exc:  # fail-closed: advisory, never auto-confirm
        logger.warning("finding_gate verify errored (finding stays advisory): %s", exc)
        return False


def gate(findings: list[dict], dispatcher=None, max_verifications: int = DEFAULT_MAX_VERIFICATIONS) -> dict:
    """Route findings: {'confirmed': [...], 'advisory': [...]}.

    Confirmed findings are safe to hand to audit_pipeline.process_audit_findings;
    advisory findings are surfaced but never become Repair Bay proposals.
    """
    dispatcher = dispatcher or _default_dispatcher
    confirmed: list[dict] = []
    advisory: list[dict] = []
    verifications_used = 0

    for finding in findings:
        if _is_deterministic(finding):
            confirmed.append({**finding, "verified_by": "deterministic"})
            continue
        if verifications_used >= max_verifications:
            advisory.append({**finding, "advisory": True, "gate_reason": "verify_budget_exhausted"})
            continue
        verifications_used += 1
        if _verify(finding, dispatcher):
            confirmed.append({**finding, "verified_by": "dhq_adversarial"})
        else:
            advisory.append({**finding, "advisory": True})

    logger.info(
        "finding_gate: %d confirmed (%d deterministic), %d advisory, %d verify dispatches",
        len(confirmed),
        sum(1 for f in confirmed if f["verified_by"] == "deterministic"),
        len(advisory),
        verifications_used,
    )
    return {"confirmed": confirmed, "advisory": advisory}
