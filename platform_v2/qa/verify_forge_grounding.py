#!/usr/bin/env python3
"""F.O.R.G.E. grounding verification harness (Phase-1 agent-optimization, project #381).

Runs ONE raw grounded code review of a PR using the EXACT review path
(`_fetch_diff` -> `_build_prompt` -> dispatch code_review) but WITHOUT writing the
``pr_reviews`` row, so independent trials can run in isolation (no row race). Reports
whether the PR's seeded FALSE-POSITIVE myth reappears under the new grounded prompt.

Run in-container:
    docker exec archie_platform python3 /app/qa/verify_forge_grounding.py --pr 1867
Optional: --myth "<regex>" to override the baked myth, --json for machine output.
"""
import argparse
import json
import re
import sys
import time

sys.path.insert(0, "/app")

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    _apply_severity_gate,
    _build_prompt,
    _fetch_diff,
)
from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    get_review,
    parse_verdict,
    poll_open_prs,
)
from tools.department_hq.services.department_dispatcher import dispatch  # noqa: E402

# The exact false-positive each PR triggered this session (2026-06-22). A grounded
# review must NOT raise these — the diffs are verified-correct.
KNOWN_MYTHS = {
    1867: r"sql[\s_-]*injection|injection\s+(vuln|risk|attack|flaw)",
    1869: r"unclosed\s+(loop|bracket|paren|brace)|infinite\s+loop|missing\s+(semicolon|closing)",
}


def _resolve_review(pr: int) -> dict:
    r = get_review(pr)
    if not r:
        poll_open_prs()
        r = get_review(pr)
    if not r:
        raise SystemExit(f"PR #{pr} not tracked in pr_reviews and poll did not find it")
    return r


def run_trial(pr: int, myth: str | None) -> dict:
    r = _resolve_review(pr)
    diff_url = r.get("diff_url") or f"https://github.com/{r['repo']}/pull/{pr}.diff"
    diff = _fetch_diff(diff_url)
    prompt = _build_prompt(r, diff)

    text = ""
    queued = False
    success = False
    for attempt in range(5):
        res = dispatch(
            capability="code_review",
            prompt=prompt,
            module_id="repair_bay",
            preferred_node=["starship_76583490e36955ab", "archie-starbase"],
        )
        success = bool(getattr(res, "success", False))
        queued = bool(getattr(res, "queued", False))
        text = (getattr(res, "response", "") or "").strip()
        if success and text:
            text = _apply_severity_gate(text)  # mirror production review_pr path
            break
        time.sleep(10)  # cold-load / queue drain (python sleep — not host shell)

    pattern = myth or KNOWN_MYTHS.get(pr, "")
    false_flag = bool(pattern) and bool(re.search(pattern, text, re.IGNORECASE))
    return {
        "pr": pr,
        "myth_pattern": pattern,
        "success": success,
        "queued_after_retries": queued and not text,
        "response_len": len(text),
        "false_flag_present": false_flag,
        "cites_evidence": "evidence:" in text.lower(),
        "verdict": parse_verdict(text) if text else None,
        "head": text[:1400],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--myth", default=None)
    ap.add_argument("--json", action="store_true", default=True)
    a = ap.parse_args()
    out = run_trial(a.pr, a.myth)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
