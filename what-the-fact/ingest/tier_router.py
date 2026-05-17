"""tier_router.py — entry point for #2943 two-tier LLM gating.

Workflow per article:
  1. Run Tier 1 via quick_analyzer.analyze_quick('bias', ...). Cheapest signal.
  2. Evaluate the gate (extreme bias, big article, special source, trending).
  3. If gate fires → run existing ai_dispatcher.analyze_with_status('deep_analysis', ...)
     and merge results. Returns analysis_tier='quick_v1+full'.
  4. Else → return a Tier-1-only payload. analysis_tier='quick_v1'.

Failure modes:
  - Tier 1 failure: skip immediately to Tier 2 (single-tier behavior) so we
    don't lose the article. analysis_tier='quick_v1_failed+full' or
    'quick_v1_failed' if Tier 2 also fails.
  - Tier 2 rate_limited: keep Tier 1 result, mark tier2_pending=true.
    Caller decides whether to retry.
  - Tier 2 failed: increment tier2_failures. Caller decides whether to
    accept Tier 1 as canonical after MAX_RETRIES (default 3).

The returned dict shape is intentionally compatible with what
ai_dispatcher.analyze_with_status() returns, plus a 'tier_meta' block
the worker uses to update the new wtf.articles tier columns.

See what-the-fact/docs/two-tier-llm-design.md for the full design.
"""

import logging
import os

from . import ai_dispatcher, quick_analyzer

logger = logging.getLogger("wtf-ingest")

_GATE_MIN_CLAIMS = int(os.environ.get("WTF_TIER2_GATE_MIN_CLAIMS", "3"))
_GATE_MIN_BODY_CHARS = int(os.environ.get("WTF_TIER2_GATE_MIN_BODY_CHARS", "1500"))
_GATE_MIN_CLUSTER_SIZE = int(os.environ.get("WTF_TIER2_GATE_MIN_CLUSTER_SIZE", "4"))
_TIER1_PREFER_NODE = os.environ.get("WTF_TIER1_PREFER_NODE", "outpost_us_001")

_GATE_BIAS_BANDS = {"left", "right"}
_GATE_SPECIAL_LEANS = {"right"}  # right-leaning balance bucket gets the full review
_GATE_SPECIAL_SLUGS = {"windspeaker", "indiginews", "kukukwes_news", "turtle_island_news"}


def _evaluate_gate(tier1: dict, body_len: int, source_slug: str,
                   source_bias_lean: str, cluster_size: int) -> tuple[bool, str]:
    """Return (gate_to_full, reason). Reason is logged so we can tune thresholds."""
    band = (tier1.get("band") or "").lower()
    if band in _GATE_BIAS_BANDS:
        return True, f"bias={band}"
    if body_len >= _GATE_MIN_BODY_CHARS:
        # Long pieces deserve a full review even if Tier 1 said 'center'.
        return True, f"body_chars={body_len}>={_GATE_MIN_BODY_CHARS}"
    if (source_bias_lean or "").lower() in _GATE_SPECIAL_LEANS:
        return True, f"source_lean={source_bias_lean}"
    if (source_slug or "").lower() in _GATE_SPECIAL_SLUGS:
        return True, f"source_slug={source_slug} (Indigenous press)"
    if cluster_size and cluster_size >= _GATE_MIN_CLUSTER_SIZE:
        return True, f"cluster_size={cluster_size}>={_GATE_MIN_CLUSTER_SIZE}"
    return False, "no gate hit"


def _tier1_only_sections(tier1: dict) -> dict:
    """Synthesize a deep_analysis-shaped dict from Tier-1 signal alone.

    The consumer page renders bias_summary + key_claims + editorial_take.
    Tier-1-only rows fill what they can; the rest stay empty until a Tier 2
    upgrade (user Deep Dive click or scheduled re-run).
    """
    band = (tier1.get("band") or "").lower() or None
    confidence = tier1.get("confidence")
    return {
        "bias_summary": {
            "band": band,
            "confidence": confidence,
            "rationale": None,         # Tier 1 didn't generate one
            "trigger_phrases": [],
            "score": None,
        },
        "key_claims": [],              # Tier 1 bias capability doesn't extract claims
        "geo_entities": [],
        "editorial_take": None,
        "confidence": confidence,
        "_tier_synthesized": True,     # marker so the consumer can show "tier-1 only" badge
    }


def analyze_tiered(article_id: int, title: str, body: str,
                   source_slug: str = "",
                   source_bias_lean: str = "",
                   cluster_size: int = 0) -> dict:
    """Run two-tier analysis. Returns:

      {
        "result": <sections dict — same shape as ai_dispatcher deep_analysis>,
        "status": "ok" | "rate_limited" | "failed",
        "tier_meta": {
            "analysis_tier": "quick_v1" | "quick_v1+full" | "quick_v1_failed" | ...,
            "tier1_ok": bool,
            "tier2_ran": bool,
            "tier2_status": "ok" | "rate_limited" | "failed" | "skipped",
            "gate_reason": str,
        }
      }

    Caller (the worker) reads tier_meta to update wtf.articles tier columns.
    """
    body_len = len(body or "")

    # ── Tier 1 ────────────────────────────────────────────────────────────
    tier1_outcome = quick_analyzer.analyze_quick(
        task="bias",
        article_id=article_id,
        title=title,
        body=body,
        source_slug=source_slug,
        prefer_node=_TIER1_PREFER_NODE,
    )
    tier1_ok = tier1_outcome["status"] == "ok" and tier1_outcome["result"] is not None
    tier1_result = tier1_outcome["result"] if tier1_ok else {}

    # ── Gate ──────────────────────────────────────────────────────────────
    if tier1_ok:
        gate, gate_reason = _evaluate_gate(
            tier1_result, body_len, source_slug, source_bias_lean, cluster_size
        )
    else:
        # Tier 1 failed → can't gate. Fall through to full so we don't lose the article.
        gate, gate_reason = True, "tier1_failed_fallback"
        logger.warning("[tier_router] article=%s tier1 failed, falling through to full", article_id)

    # ── Tier 2 (selective) ────────────────────────────────────────────────
    if not gate:
        logger.debug("[tier_router] article=%s gate=skip (%s)", article_id, gate_reason)
        return {
            "result": _tier1_only_sections(tier1_result),
            "status": "ok",
            "tier_meta": {
                "analysis_tier": "quick_v1",
                "tier1_ok": True,
                "tier2_ran": False,
                "tier2_status": "skipped",
                "gate_reason": gate_reason,
            },
        }

    tier2_outcome = ai_dispatcher.analyze_with_status(
        task="deep_analysis",
        article_id=article_id,
        title=title,
        body=body,
        source_slug=source_slug,
    )
    tier2_status = tier2_outcome["status"]

    if tier2_status == "ok":
        return {
            "result": tier2_outcome["result"],
            "status": "ok",
            "tier_meta": {
                "analysis_tier": "quick_v1+full" if tier1_ok else "quick_v1_failed+full",
                "tier1_ok": tier1_ok,
                "tier2_ran": True,
                "tier2_status": "ok",
                "gate_reason": gate_reason,
            },
        }

    # Tier 2 didn't complete cleanly. Preserve Tier 1 if we have it.
    if tier1_ok:
        return {
            "result": _tier1_only_sections(tier1_result),
            "status": "ok",     # the worker still persists Tier 1 — overall flow continues
            "tier_meta": {
                "analysis_tier": "quick_v1",
                "tier1_ok": True,
                "tier2_ran": True,
                "tier2_status": tier2_status,
                "gate_reason": gate_reason,
                "tier2_pending": True,
            },
        }
    # Tier 1 also failed — no result for this article this cycle.
    return {
        "result": None,
        "status": tier2_status,   # propagate so the worker counts it correctly
        "tier_meta": {
            "analysis_tier": "pending",
            "tier1_ok": False,
            "tier2_ran": True,
            "tier2_status": tier2_status,
            "gate_reason": gate_reason,
        },
    }


def _factcheck_gate(tier1_claims: list, body_len: int, source_slug: str,
                    source_bias_lean: str, cluster_size: int) -> tuple[bool, str]:
    """Gate for factcheck-tier flow. Same shape as _evaluate_gate but the primary
    signal is claim count (Tier-1 extracts claims with no verdict; Tier-2 adds verdicts)."""
    n_claims = len(tier1_claims or [])
    if n_claims >= _GATE_MIN_CLAIMS and body_len >= _GATE_MIN_BODY_CHARS:
        return True, f"claims={n_claims}>=3 + body={body_len}>=1500"
    if (source_bias_lean or "").lower() in _GATE_SPECIAL_LEANS:
        return True, f"source_lean={source_bias_lean}"
    if (source_slug or "").lower() in _GATE_SPECIAL_SLUGS:
        return True, f"source_slug={source_slug} (Indigenous press)"
    if cluster_size and cluster_size >= _GATE_MIN_CLUSTER_SIZE:
        return True, f"cluster_size={cluster_size}>={_GATE_MIN_CLUSTER_SIZE}"
    return False, f"no gate hit (claims={n_claims}, body={body_len})"


def _factcheck_tier1_only(tier1: dict) -> dict:
    """Synthesize a fact_check-shaped dict from Tier-1 claim list alone.

    The fact_check table expects claims with verdict + reasoning. Tier 1 only
    extracted claim text — fill verdict=unverifiable + empty reasoning so the
    row is valid but clearly marked as Tier-1-only (consumer can show badge).
    """
    raw_claims = tier1.get("claims") or []
    return {
        "claims": [
            {"text": c, "verdict": "unverifiable", "reasoning": ""}
            for c in raw_claims if isinstance(c, str)
        ],
        "overall_verdict": "unverifiable",
        "confidence": 0.0,
        "_tier_synthesized": True,
    }


def analyze_factcheck_tiered(article_id: int, title: str, body: str,
                             source_slug: str = "",
                             source_bias_lean: str = "",
                             cluster_size: int = 0) -> dict:
    """Two-tier factcheck. Returns same shape as analyze_tiered() — caller persists
    tier_meta into wtf.articles.

    Tier 1: factcheck_quick → claim list (no verdicts).
    Gate: >=3 claims AND >=1500 char body, OR right-lean/Indigenous/trending source.
    Tier 2: existing ai_dispatcher 'factcheck' → claims + verdicts + reasoning.
    """
    body_len = len(body or "")

    # Tier 1
    tier1_outcome = quick_analyzer.analyze_quick(
        task="factcheck",
        article_id=article_id,
        title=title,
        body=body,
        source_slug=source_slug,
        prefer_node=_TIER1_PREFER_NODE,
    )
    tier1_ok = tier1_outcome["status"] == "ok" and tier1_outcome["result"] is not None
    tier1_result = tier1_outcome["result"] if tier1_ok else {}
    tier1_claims = tier1_result.get("claims") if tier1_ok else []

    # Gate
    if tier1_ok:
        gate, gate_reason = _factcheck_gate(
            tier1_claims, body_len, source_slug, source_bias_lean, cluster_size
        )
    else:
        gate, gate_reason = True, "tier1_failed_fallback"
        logger.warning("[tier_router] factcheck article=%s tier1 failed, falling through", article_id)

    if not gate:
        logger.debug("[tier_router] factcheck article=%s gate=skip (%s)", article_id, gate_reason)
        return {
            "result": _factcheck_tier1_only(tier1_result),
            "status": "ok",
            "tier_meta": {
                "analysis_tier": "quick_v1",
                "tier1_ok": True,
                "tier2_ran": False,
                "tier2_status": "skipped",
                "gate_reason": gate_reason,
            },
        }

    tier2_outcome = ai_dispatcher.analyze_with_status(
        task="factcheck",
        article_id=article_id,
        title=title,
        body=body,
        source_slug=source_slug,
    )
    tier2_status = tier2_outcome["status"]

    if tier2_status == "ok":
        return {
            "result": tier2_outcome["result"],
            "status": "ok",
            "tier_meta": {
                "analysis_tier": "quick_v1+full" if tier1_ok else "quick_v1_failed+full",
                "tier1_ok": tier1_ok,
                "tier2_ran": True,
                "tier2_status": "ok",
                "gate_reason": gate_reason,
            },
        }

    # Tier 2 hiccup — preserve Tier 1 if we have it.
    if tier1_ok:
        return {
            "result": _factcheck_tier1_only(tier1_result),
            "status": "ok",
            "tier_meta": {
                "analysis_tier": "quick_v1",
                "tier1_ok": True,
                "tier2_ran": True,
                "tier2_status": tier2_status,
                "gate_reason": gate_reason,
                "tier2_pending": True,
            },
        }
    return {
        "result": None,
        "status": tier2_status,
        "tier_meta": {
            "analysis_tier": "pending",
            "tier1_ok": False,
            "tier2_ran": True,
            "tier2_status": tier2_status,
            "gate_reason": gate_reason,
        },
    }
