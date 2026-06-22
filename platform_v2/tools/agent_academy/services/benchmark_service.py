"""Benchmark Service — runs model comparisons and updates Roster assignments.

Flow: run_benchmark() → store results → analyze_results() → update_roster()
"""

import logging

from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)

# Skill categories map to model families
SKILL_CATEGORIES = {
    "code": "Code generation, debugging, refactoring",
    "analysis": "Data analysis, reasoning, investigation",
    "writing": "Content creation, documentation, creative writing",
    "conversation": "Chat, support, Q&A",
    "translation": "Language translation, i18n",
    "vision": "Image analysis, visual tasks",
    "lightweight": "Simple tasks, notifications, status checks",
    "web_interaction": "Browser automation, social media posting, web form fill",
}


def store_benchmark_result(
    agent_id,
    model_name,
    skill_category,
    score,
    response_time_ms=None,
    quality_rating=None,
    tokens_used=None,
    task_description=None,
    metadata=None,
):
    """Store a single benchmark result."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO agent_benchmark_results
                (agent_id, model_name, skill_category, score, response_time_ms,
                 quality_rating, tokens_used, task_description, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                agent_id,
                model_name,
                skill_category,
                score,
                response_time_ms,
                quality_rating,
                tokens_used,
                task_description,
                Json(metadata) if metadata else None,
            ),
        )
        return cur.fetchone()["id"]


def grade_response(task_description, response, skill_category=None, reference=None, grader="V.E.R.I.F.Y."):
    """P2-A (#381) correctness grader — the KEYSTONE of Phase 2.

    Returns a 0-5 CORRECTNESS score for an agent's response, judged by a LOCAL grader agent
    (strictly sovereign — no cloud, Phase-2 decision 3). This is the quality signal that
    right-sizing + auto-promotion rank by; today's benchmark ``score`` is length/speed-biased,
    which is why a fast-but-wrong small model could look 'best'.

    Returns ``{"score": float|None, "rationale": str, "grader": str}``. ``score`` is None on
    grader failure so the caller SKIPS storing (never a bogus 0 that corrupts model selection).
    """
    if not response or not str(response).strip():
        return {"score": 0.0, "rationale": "empty response", "grader": grader}
    rubric = (
        "You are a STRICT correctness grader. Score the RESPONSE to the TASK on a 0-5 scale:\n"
        "5 = fully correct + complete; 4 = correct with minor omissions; 3 = partially correct; "
        "2 = mostly wrong but some merit; 1 = wrong; 0 = empty / irrelevant / refused.\n"
        "Judge CORRECTNESS ONLY — ignore length, style, and speed. A short correct answer beats a "
        "long wrong one.\n"
    )
    ref = f"\nREFERENCE (ground truth):\n{reference}\n" if reference else ""
    prompt = (
        rubric
        + (f"SKILL: {skill_category}\n" if skill_category else "")
        + f"\nTASK:\n{task_description}\n{ref}\nRESPONSE TO GRADE:\n{response}\n\n"
        + 'Return ONLY JSON: {"score": <number 0-5>, "rationale": "<one sentence>"}.'
    )
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        res = dispatch(
            capability="classify",
            prompt=prompt,
            module_id="agent_academy",
            json_mode=True,
            local_only=True,  # sovereign grader — never escalate to cloud (decision 3)
            prefer_agent=grader,
        )
        if not (getattr(res, "success", False) and getattr(res, "response", "")):
            return {"score": None, "rationale": "grader unavailable", "grader": grader}
        import json as _json
        import re as _re

        s = (res.response or "").strip()
        m = _re.search(r"\{.*\}", s, _re.S)
        if m:
            s = m.group(0)
        d = _json.loads(s)
        sc = max(0.0, min(5.0, float(d.get("score"))))
        return {"score": sc, "rationale": (d.get("rationale") or "")[:300], "grader": grader}
    except Exception as e:
        logger.debug("[Benchmark] grade_response failed: %s", e)
        return {"score": None, "rationale": "grade error", "grader": grader}


def grade_and_store(
    agent_id,
    model_name,
    skill_category,
    task_description,
    response,
    response_time_ms=None,
    tokens_used=None,
    reference=None,
    grader="V.E.R.I.F.Y.",
):
    """Grade a benchmarked response for CORRECTNESS (P2-A) and store it as the PRIMARY ``score``.
    Speed/tokens stay in their columns + metadata so they remain visible but no longer drive model
    selection. Returns the result id, or None if grading failed (then nothing is stored)."""
    g = grade_response(task_description, response, skill_category, reference, grader)
    if g.get("score") is None:
        return None
    return store_benchmark_result(
        agent_id=agent_id,
        model_name=model_name,
        skill_category=skill_category,
        score=g["score"],
        response_time_ms=response_time_ms,
        quality_rating=g["score"],
        tokens_used=tokens_used,
        task_description=task_description,
        metadata={
            "grader": g["grader"],
            "rationale": g["rationale"],
            "score_kind": "correctness_0_5",
            "response_len": len(str(response)),
        },
    )


def get_best_model_per_category(days=30):
    """Analyze benchmark results to find the best model per skill category.

    Returns: {skill_category: {"model": name, "avg_score": float, "samples": int}}
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT skill_category, model_name,
                   AVG(score) as avg_score,
                   AVG(quality_rating) as avg_quality,
                   AVG(response_time_ms) as avg_time,
                   COUNT(*) as samples
            FROM agent_benchmark_results
            WHERE benchmark_date > NOW() - INTERVAL '%s days'
              AND score IS NOT NULL
            GROUP BY skill_category, model_name
            HAVING COUNT(*) >= 3
            ORDER BY skill_category, avg_score DESC
        """,
            (days,),
        )

        best = {}
        for r in cur.fetchall():
            cat = r["skill_category"]
            if cat not in best:  # first row per category = highest avg_score
                best[cat] = {
                    "model": r["model_name"],
                    "avg_score": float(r["avg_score"]),
                    "avg_quality": float(r["avg_quality"]) if r["avg_quality"] else None,
                    "avg_time_ms": int(r["avg_time"]) if r["avg_time"] else None,
                    "samples": r["samples"],
                }
        return best


def update_roster_models(dry_run=True):
    """Update agents.model based on best benchmark results per skill category.

    Matches agents to skill categories via their primary skill_category field
    or department-based defaults.

    Args:
        dry_run: If True, return proposed changes without applying them

    Returns: list of {agent_id, agent_name, old_model, new_model, category}
    """
    best = get_best_model_per_category()
    if not best:
        logger.info("No benchmark results — skipping roster model update")
        return []

    # Map departments to default skill categories (shared module constant).
    DEPT_SKILL_MAP = _DEPT_SKILL_MAP

    # Read agent roster
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, name, display_name, model, department,
                   capabilities->>'skill_category' as skill_cat
            FROM agents
            WHERE shift_state NOT IN ('decommissioned')
        """
        )
        agents = [dict(r) for r in cur.fetchall()]

    changes = []
    for agent in agents:
        # Determine skill category: explicit > department default
        cat = agent["skill_cat"] or DEPT_SKILL_MAP.get(agent["department"])
        if not cat or cat not in best:
            continue

        new_model = best[cat]["model"]
        old_model = agent["model"] or ""

        if new_model != old_model:
            changes.append(
                {
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "display_name": agent["display_name"],
                    "old_model": old_model,
                    "new_model": new_model,
                    "category": cat,
                }
            )
            if not dry_run:
                from services.agent_service import update_agent

                update_agent(agent["id"], model=new_model)
                logger.info(
                    "Updated %s model: %s -> %s (category: %s)",
                    agent["name"],
                    old_model,
                    new_model,
                    cat,
                )

    action = "Would update" if dry_run else "Updated"
    logger.info("%s %d agent model assignments", action, len(changes))
    return changes


# Department -> default skill_category, used by roster model selection (P2-A / P2-C).
_DEPT_SKILL_MAP = {
    "Engineering & Technology": "code",
    "Research & Development": "code",
    "Security & Compliance": "analysis",
    "Analytics & Intelligence": "analysis",
    "Creative & Design": "writing",
    "Documentation & Knowledge": "writing",
    "Marketing & Communications": "writing",
    "Customer Success & Support": "conversation",
    "Diplomatic & External Relations": "conversation",
    "Human Resources & Culture": "conversation",
    "Executive Office": "analysis",
    "Operations & Infrastructure": "lightweight",
    "Logistics & Supply Chain": "lightweight",
    "Finance & Accounting": "analysis",
    "Medical & Wellness": "analysis",
    "Legal & Regulatory": "analysis",
    "News & Media": "writing",
}


def _category_model_correctness(days=30, min_samples=5):
    """Per (skill_category, model): avg CORRECTNESS (P2-A grades ONLY), avg time, samples — sorted
    best-correctness-first per category. Filters score_kind='correctness_0_5' so stale length/speed
    scores never drive right-sizing."""
    cats = {}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT skill_category, model_name,
                   AVG(score) AS avg_score, AVG(response_time_ms) AS avg_time, COUNT(*) AS samples
            FROM agent_benchmark_results
            WHERE benchmark_date > NOW() - INTERVAL '%s days'
              AND score IS NOT NULL
              AND COALESCE(metadata->>'score_kind', '') = 'correctness_0_5'
            GROUP BY skill_category, model_name
            HAVING COUNT(*) >= %s
            ORDER BY skill_category, AVG(score) DESC
            """,
            (days, min_samples),
        )
        for r in cur.fetchall():
            cats.setdefault(r["skill_category"], []).append(
                {
                    "model": r["model_name"],
                    "avg_score": float(r["avg_score"]),
                    "avg_time": int(r["avg_time"]) if r["avg_time"] is not None else None,
                    "samples": int(r["samples"]),
                }
            )
    return cats


def _rightsized_choice(models, quality_tolerance=0.15):
    """Pareto right-sizing: from per-model correctness for ONE category (best-first), return the
    FASTEST model whose correctness is within ``quality_tolerance`` of the best — the smallest/fastest
    model that HOLDS quality, NOT the highest-scoring (which could be a needlessly big model)."""
    best = models[0]["avg_score"]
    cands = [m for m in models if m["avg_score"] >= best - quality_tolerance]
    return min(cands, key=lambda m: m["avg_time"] if m["avg_time"] is not None else 10**12)


def propose_model_rightsizing(quality_tolerance=0.15, days=30, min_samples=5):
    """P2-C (#381): propose CORRECTNESS-graded, Pareto right-sized model swaps for the roster — the
    smallest/fastest model that holds quality per P2-A grades. READ-ONLY: returns proposals; applying
    is Tier-2 gated (owner approval via Telegram), NEVER automatic. Returns [] when there is no graded
    data yet (a benchmark producer must run first)."""
    cats = _category_model_correctness(days, min_samples)
    if not cats:
        return []
    rightsized = {cat: _rightsized_choice(ms, quality_tolerance) for cat, ms in cats.items()}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, name, display_name, model, department,
                   capabilities->>'skill_category' AS skill_cat
            FROM agents
            WHERE shift_state NOT IN ('decommissioned')
            """
        )
        agents = [dict(r) for r in cur.fetchall()]
    proposals = []
    for a in agents:
        cat = a["skill_cat"] or _DEPT_SKILL_MAP.get(a["department"])
        if not cat or cat not in rightsized:
            continue
        choice = rightsized[cat]
        old_model = a["model"] or ""
        if choice["model"] != old_model:
            proposals.append(
                {
                    "agent_id": a["id"],
                    "agent_name": a["name"],
                    "display_name": a["display_name"],
                    "category": cat,
                    "old_model": old_model,
                    "new_model": choice["model"],
                    "new_avg_correctness": round(choice["avg_score"], 2),
                    "best_avg_correctness": round(cats[cat][0]["avg_score"], 2),
                    "new_avg_time_ms": choice["avg_time"],
                    "samples": choice["samples"],
                }
            )
    return proposals


def get_benchmark_summary():
    """Summary stats for the Academy UI."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT skill_category, COUNT(DISTINCT model_name) as models_tested,
                   COUNT(*) as total_runs, MAX(benchmark_date) as latest
            FROM agent_benchmark_results
            GROUP BY skill_category
            ORDER BY skill_category
        """
        )
        categories = []
        for r in cur.fetchall():
            row = dict(r)
            row["latest"] = str(row["latest"]) if row["latest"] else None
            categories.append(row)

        cur.execute("SELECT COUNT(*) as cnt FROM agent_benchmark_results")
        total = cur.fetchone()["cnt"]

    return {
        "total_benchmarks": total,
        "categories": categories,
        "best_models": get_best_model_per_category(),
    }
