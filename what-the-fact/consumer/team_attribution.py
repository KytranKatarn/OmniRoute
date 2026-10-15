"""Small pure helpers for /team: card initials, and an honest breakdown of the 'unattributed' work.

Pure and stdlib-only. Found 2026-10-15: the 'Who actually did the work' chart showed only 'unattributed' (5,941), because in a given 24 h window almost
no row records an agent. Over 24 h only ~3.5% of FACT-CHECKS name one (166 of ~4,700); ~3,000 came from the Tier-1 quick model, which records no agent at all.
(analysis_tier exists on wtf.fact_checks only, not on bias_scores.) 'Unattributed' is true but unhelpful when the tier IS recorded, so the bucket is
explained by tier instead of left opaque.
"""

import re

# analysis_tier values written by ingest/tier_router.py -> a plain-English description of HOW the score was produced (never a made-up agent).
TIER_LABELS = {
    "quick_v1": "Tier-1 quick triage (small model)",
    "quick_v1+full": "Tier-1 triage, then the full model",
    "quick_v1_failed+full": "Tier-1 failed, so the full model ran",
}
NO_TIER = "no tier recorded"


def initials(name, length=2):
    """'P.R.O.O.F.' -> 'PR', 'V.E.R.I.F.Y.-B' -> 'VE'. Letters only; '?' if there are none."""
    letters = re.findall(r"[A-Za-z]", name or "")
    return "".join(letters[:length]).upper() or "?"


def unattributed_breakdown(by_tier):
    """[{'label', 'events'}] largest first, from {analysis_tier: count} for fact-checks with no agent recorded. Unknown or empty tiers are grouped as NO_TIER."""
    merged = {}
    for tier, n in (by_tier or {}).items():
        n = int(n or 0)
        if n <= 0:
            continue
        label = TIER_LABELS.get((tier or "").strip(), NO_TIER)
        merged[label] = merged.get(label, 0) + n
    return [{"label": k, "events": v} for k, v in sorted(merged.items(), key=lambda kv: -kv[1])]
