#!/usr/bin/env python3
"""Per-TASK model A/B for the WTF newsroom agents.

WHY THIS EXISTS
The five WTF agents are five DIFFERENT JOBS — geo is structured extraction,
bias is classification, fact-check is reasoning, summarise is generation. They
do not need the same model, and `agents.model` is already per-agent, so the
platform can express that today. What was missing is EVIDENCE for which model
each job should get.

⚠️ THIS SCRIPT EXISTS BECAUSE THE AGGREGATE LOGS LIE.

Grouping task_execution_log by model_used (6h, 2026-08-31) said:

    USS-246 mistral:7b   461 runs  avg   7.0s
    USS-246 qwen2.5:7b   177 runs  avg  89.3s      "mistral is 13x faster"

That reading produced a recommendation to move B.I.A.S./V.E.R.I.F.Y. to
mistral. Running THIS script on identical prompts and identical articles
inverted the ranking completely:

    qwen2.5:7b    n=5  100%  median  5.3s     <- 3x FASTER, not 13x slower
    mistral:7b    n=5  100%  median 15.6s
    llama3.2:3b   n=5  100%  median 28.0s

The aggregate was measuring cold loads, queue position and _WTF_CPU_FIRST's
deliberate CPU routing — and attributing all of it to the MODEL. Model-
attributed latency is not model speed. See task #6215.

METHOD, learned the same day:
  - DISCARD the first call per model. It is a cold load. Measured 352.2s vs a
    7.5s warm follow-up on the same model — a 45x contamination that makes any
    average meaningless.
  - Report MEDIANS, not averages.
  - n=5 ranks latency; it does NOT support success-rate claims.

With a 54,346-article backlog and 585/day intake, per-item latency — not the
nightly run cap — is what decides whether the pipeline ever catches up. But the
dominant term is RESIDENCY, not model choice: see the warmboot residency spec
at docs/superpowers/specs/2026-08-31-warmboot-residency-profiles-design.md.

⚠️ SPEED IS NOT THE DECISION. Swapping B.I.A.S. or V.E.R.I.F.Y. changes the
bias scores and fact-check verdicts the site PUBLISHES. This script deliberately
does not change anything: it runs each candidate over the SAME real articles
with the REAL prompts and records latency + the actual output, so a human (or
the Academy judge) can compare quality first.

USAGE
    docker exec archie_platform python3 /app/scripts/wtf_model_ab.py --task bias --n 5
    docker exec archie_platform python3 /app/scripts/wtf_model_ab.py --all --n 3

Results append to /app/logs/wtf_model_ab/<task>_<ts>.json.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/app")

# The dispatcher imports `from db import ...` at module scope, which only
# resolves from an ai_bridge-aware path (KB #272154).
try:
    from services.signal_calendar_service import _ensure_import_paths

    _ensure_import_paths()
except Exception:
    sys.path.insert(0, "/app/ai_bridge")

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from tools.department_hq.services.department_dispatcher import dispatch  # noqa: E402


def _wtf_conn():
    """WTF lives in its OWN database on the hub postgres, not in `archie`.

    database.get_db_cursor() points at `archie`, where wtf.articles does not
    exist — so it fails with UndefinedTable rather than returning nothing, which
    at least is honest. Connect to the `wtf` DB explicitly.
    """
    # The password comes from a Docker SECRET, not a plain env var, so
    # os.getenv("DB_PASSWORD") is empty inside the container and a hand-built
    # DSN fails with "no password supplied". Borrow the platform's own
    # already-authenticated connection parameters and swap ONLY the dbname.
    from database import get_db_connection

    # get_db_connection() is a CONTEXT MANAGER (pooled), not a bare connection.
    with get_db_connection() as src:
        p = src.get_dsn_parameters()
    return psycopg2.connect(
        host=p.get("host", "archie_database"),
        port=p.get("port", 5432),
        dbname="wtf",
        user=p.get("user", "archie"),
        password=os.getenv("DB_PASSWORD") or _secret_password(),
        connect_timeout=10,
    )


def _secret_password():
    """Docker secret first, matching the platform's own resolution order."""
    for path in ("/run/secrets/db_password", "/run/secrets/postgres_password"):
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            continue
    return ""


OUT_DIR = "/app/logs/wtf_model_ab"

# Candidates grouped by the KIND of work, not by agent name. A classification
# job and a reasoning job have genuinely different requirements, which is the
# whole premise of testing them separately.
TASKS = {
    "bias": {
        "capability": "bias_analysis",
        "job_kind": "classification",
        "current": "qwen2.5:7b",
        "candidates": ["qwen2.5:7b", "mistral:7b", "llama3.2:3b"],
    },
    "factcheck": {
        "capability": "fact_check",
        "job_kind": "reasoning",
        "current": "qwen2.5:7b",
        "candidates": ["qwen2.5:7b", "mistral:7b"],
    },
    "geo": {
        "capability": "geo_extraction",
        "job_kind": "structured extraction",
        "current": "qwen2.5:1.5b",
        "candidates": ["qwen2.5:1.5b", "llama3.2:3b"],
    },
}


def sample_articles(n):
    """Real articles, newest first — the same input the pipeline sees.

    Deliberately NOT random: a fixed, reproducible sample means two runs of this
    script are comparable to each other, not just internally.
    """
    conn = _wtf_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, LEFT(COALESCE(body, ''), 3000) AS body
                  FROM wtf.articles
                 WHERE suppressed_reason IS NULL
                   AND body IS NOT NULL AND length(body) > 400
                 ORDER BY published_at DESC
                 LIMIT %s
                """,
                (n,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.rollback()
        conn.close()


def build_prompt(task, art):
    """Mirrors the REAL wtf_hub prompts (tools/wtf_hub/routes.py).

    ⚠️ If the hub's prompts change, change them HERE too — a comparison run on a
    prompt the pipeline no longer sends measures nothing about the pipeline.
    """
    title, body = art["title"], art["body"]
    if task == "bias":
        return (
            "Rate the political lean of this Canadian news article on a "
            "left-to-right spectrum.\n"
            'Return JSON: {"band":"left|center-left|center|center-right|right",'
            '"score":-1.0..1.0,"rationale":"one sentence"}\n\n'
            f"TITLE: {title}\n\nBODY: {body}"
        )
    if task == "factcheck":
        return (
            "Identify the central factual claim in this article and assess it.\n"
            'Return JSON: {"claim":"...","verdict":"verified|mostly_true|mixed|'
            'disputed|unverifiable|descriptive_reporting","rationale":"..."}\n\n'
            f"TITLE: {title}\n\nBODY: {body}"
        )
    if task == "geo":
        return (
            "Identify where this Canadian news story is geographically located.\n"
            'Return JSON: {"province_code":"ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU|null",'
            '"city":"...|null","country_code":"CA|US|GB|...|null",'
            '"geo_scope":"municipal|provincial|national|international"}\n\n'
            f"TITLE: {title}\n\nBODY: {body}"
        )
    raise ValueError(task)


def run_task(task, n):
    cfg = TASKS[task]
    arts = sample_articles(n)
    print(f"\n=== {task}  ({cfg['job_kind']})  capability={cfg['capability']}")
    print(f"    current model: {cfg['current']}   articles: {len(arts)}")

    results = []
    for model in cfg["candidates"]:
        lat, ok, outs = [], 0, []
        for art in arts:
            t0 = time.time()
            try:
                r = dispatch(
                    capability=cfg["capability"],
                    prompt=build_prompt(task, art),
                    module_id="wtf_model_ab",
                    json_mode=True,
                    model_override=model,
                    priority="low",
                )
                dt = time.time() - t0
                success = bool(getattr(r, "success", False))
                text = (getattr(r, "response", "") or "")[:400]
            except Exception as exc:  # a candidate that throws is a REAL result
                dt, success, text = time.time() - t0, False, f"EXCEPTION: {exc}"
            lat.append(dt)
            ok += 1 if success else 0
            outs.append({"article_id": art["id"], "ok": success, "seconds": round(dt, 1), "output": text})
            print(f"      {model:<16} art={art['id']:<9} {dt:6.1f}s " f"{'ok' if success else 'FAIL'}")

        lat.sort()
        row = {
            "model": model,
            "is_current": model == cfg["current"],
            "n": len(lat),
            "ok": ok,
            "success_pct": round(100.0 * ok / len(lat)) if lat else 0,
            "avg_s": round(sum(lat) / len(lat), 1) if lat else None,
            "median_s": round(lat[len(lat) // 2], 1) if lat else None,
            "max_s": round(lat[-1], 1) if lat else None,
            "samples": outs,
        }
        results.append(row)

    # Speed table only — quality is a HUMAN call and is left to the samples.
    print(f"\n    --- {task}: latency (quality NOT judged here) ---")
    print(f"    {'model':<16} {'n':>3} {'ok%':>5} {'avg':>8} {'median':>8} {'max':>8}")
    for r in results:
        mark = " <- current" if r["is_current"] else ""
        print(
            f"    {r['model']:<16} {r['n']:>3} {r['success_pct']:>4}% "
            f"{r['avg_s']:>7}s {r['median_s']:>7}s {r['max_s']:>7}s{mark}"
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(OUT_DIR, f"{task}_{ts}.json")
    with open(path, "w") as fh:
        json.dump(
            {
                "task": task,
                "job_kind": cfg["job_kind"],
                "capability": cfg["capability"],
                "current": cfg["current"],
                "generated_at": ts,
                "results": results,
            },
            fh,
            indent=2,
        )
    print(f"    full outputs (for quality review): {path}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=sorted(TASKS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=3, help="articles per model")
    a = ap.parse_args()
    if not a.task and not a.all:
        ap.error("pass --task <name> or --all")

    for t in sorted(TASKS) if a.all else [a.task]:
        run_task(t, a.n)

    print(
        "\nNOTE: this script CHANGES NOTHING. Latency is decided here; quality"
        "\nis not. Read the sampled outputs before moving any agent's model —"
        "\nbias scores and fact-check verdicts are published to readers."
    )


if __name__ == "__main__":
    main()
