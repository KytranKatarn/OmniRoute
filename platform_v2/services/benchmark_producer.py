"""Benchmark PRODUCER (P2-PRODUCER, project #381).

Generates the correctness-graded data that the rest of Phase 2 needs. For each task in a small
per-capability suite, it runs the SAME task on each candidate model (forced via model_override),
then grades the response with P2-A's correctness grader (grade_and_store). The result lands in
agent_benchmark_results as score_kind='correctness_0_5' rows — which ACTIVATES the grader and gives
P2-C (right-sizing) real data to propose from.

Sovereign: every dispatch is local_only. Capped per call. The model that ACTUALLY ran is recorded
(DispatchResult.model_used), so a fallback never mislabels a row.

Wire ``scheduled_benchmark_cycle`` into the scheduler (off-peak cron) to build the corpus over time.
"""

import logging
import time

logger = logging.getLogger(__name__)

# Small per-category suite. Tasks have a clear correct answer so correctness grading is meaningful.
BENCHMARK_SUITE = {
    "lightweight": [
        {
            "prompt": "Classify the sentiment as exactly one word (positive/negative/neutral): "
            "'I absolutely love this, best purchase ever!'",
            "reference": "positive",
        },
        {
            "prompt": "Extract the year from this text, digits only: "
            "'The treaty was signed in 1994 after years of talks.'",
            "reference": "1994",
        },
        {"prompt": "Reply with only the capital city of Japan.", "reference": "Tokyo"},
    ],
    "code": [
        {
            "prompt": "Write a Python function `add(a, b)` that returns the sum of a and b. Code only.",
            "reference": "def add(a, b):\n    return a + b",
        },
        {
            "prompt": "Write a Python function `is_even(n)` returning True if n is even. Code only.",
            "reference": "def is_even(n):\n    return n % 2 == 0",
        },
        {
            "prompt": "In Python, write a one-line expression that reverses the string variable s.",
            "reference": "s[::-1]",
        },
    ],
    "analysis": [
        {
            "prompt": "A train travels 60 km in 1.5 hours. What is its average speed in km/h? "
            "Answer with just the number.",
            "reference": "40",
        },
        {"prompt": "If 3 pens cost $6, how much do 5 pens cost in dollars? Just the number.", "reference": "10"},
        {"prompt": "What is 15% of 200? Just the number.", "reference": "30"},
    ],
}

# skill_category -> a representative dispatch capability (routing only; model_override forces the model).
_CATEGORY_CAPABILITY = {
    "lightweight": "classify",
    "code": "code",
    "analysis": "analyze",
    "writing": "summarize",
    "conversation": "support",
    "translation": "translate",
}

# Candidate models to compare (hub warm set, ascending capability). gemma3:12b can be added once the
# small models are baselined.
CANDIDATE_MODELS = ["qwen2.5:1.5b", "llama3.2:3b", "qwen2.5:7b"]


def run_benchmark_cycle(categories=None, models=None, repeats=1, max_dispatches=120, local_only=True):
    """Run the suite across candidate models and grade each response (P2-A). READ side-effect = it
    INSERTS correctness-graded rows into agent_benchmark_results (that is the point). Sovereign +
    capped. Returns ``{"dispatched", "stored", "skipped"}``."""
    from tools.agent_academy.services.benchmark_service import grade_and_store
    from tools.department_hq.services.department_dispatcher import dispatch

    cats = categories or list(BENCHMARK_SUITE.keys())
    mods = models or CANDIDATE_MODELS
    out = {"dispatched": 0, "stored": 0, "skipped": 0}
    for cat in cats:
        cap = _CATEGORY_CAPABILITY.get(cat, "classify")
        for task in BENCHMARK_SUITE.get(cat, []):
            for model in mods:
                for _ in range(repeats):
                    if out["dispatched"] >= max_dispatches:
                        logger.info("[benchmark_producer] hit max_dispatches=%s", max_dispatches)
                        return out
                    t0 = time.time()
                    try:
                        res = dispatch(
                            capability=cap,
                            prompt=task["prompt"],
                            module_id="benchmark_producer",
                            model_override=model,
                            local_only=local_only,
                        )
                    except Exception as exc:
                        logger.debug("[benchmark_producer] dispatch error (%s/%s): %s", cat, model, exc)
                        out["skipped"] += 1
                        continue
                    out["dispatched"] += 1
                    if not (getattr(res, "success", False) and getattr(res, "response", "")):
                        out["skipped"] += 1
                        continue
                    dt_ms = int((time.time() - t0) * 1000)
                    rid = grade_and_store(
                        agent_id=None,  # model-centric benchmark (agent_id is nullable)
                        model_name=getattr(res, "model_used", "") or model,
                        skill_category=cat,
                        task_description=task["prompt"][:200],
                        response=res.response,
                        response_time_ms=dt_ms,
                        reference=task.get("reference"),
                    )
                    if rid:
                        out["stored"] += 1
                    else:
                        out["skipped"] += 1
    logger.info("[benchmark_producer] cycle: %s", out)
    return out


def _producer_enabled():
    """platform_settings benchmark_producer_enabled (default OFF — owner-gated; the cycle consumes
    inference, so it stays off until explicitly scheduled/enabled). Fail-safe to False."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'benchmark_producer_enabled'")
            row = cur.fetchone()
        if not row:
            return False
        val = row.get("value") if isinstance(row, dict) else row[0]
        return bool(val) and str(val).lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


def scheduled_benchmark_cycle():
    """Scheduler entry point — runs one conservative cycle when benchmark_producer_enabled is ON.
    Register off-peak (e.g. nightly). Default OFF so it never runs until you turn it on."""
    if not _producer_enabled():
        return {"skipped_disabled": True}
    return run_benchmark_cycle(repeats=2, max_dispatches=80)
