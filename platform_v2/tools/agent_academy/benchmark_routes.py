"""
Agent Academy — Benchmark Routes

Run benchmarks, view results, rank agents by capability.
"""

import json
import logging
import time

from flask import jsonify, request, Response
from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_benchmark_routes(bp, admin_required):
    """Register benchmark API routes on the blueprint."""

    @bp.route("/api/benchmarks")
    @admin_required
    def list_benchmarks():
        """List recent benchmark runs with results."""
        limit = request.args.get("limit", 20, type=int)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT r.id, r.action_key, r.station_code, r.status,
                          r.total_agents, r.completed_agents, r.failed_agents,
                          r.started_at, r.completed_at, r.test_config, r.metadata
                   FROM action_benchmark_runs r
                   ORDER BY r.started_at DESC
                   LIMIT %s""",
                (limit,),
            )
            runs = [dict(row) for row in cur.fetchall()]

            # Attach results for each run
            for run in runs:
                cur.execute(
                    """SELECT br.id, br.agent_id, br.agent_name, br.display_name,
                              br.model_used, br.duration_ms, br.success, br.score,
                              br.response_preview, br.tested_at
                       FROM action_benchmark_results br
                       WHERE br.run_id = %s
                       ORDER BY br.score DESC
                       LIMIT 10""",
                    (run["id"],),
                )
                run["results"] = [dict(r) for r in cur.fetchall()]
                # Serialize datetime/jsonb for JSON
                run["started_at"] = str(run["started_at"]) if run["started_at"] else None
                run["completed_at"] = str(run["completed_at"]) if run["completed_at"] else None
                run["test_config"] = run["test_config"] or {}
                run["metadata"] = run["metadata"] or {}
                for r in run["results"]:
                    r["tested_at"] = str(r["tested_at"]) if r["tested_at"] else None

        return jsonify({"runs": runs})

    @bp.route("/api/benchmarks/run", methods=["POST"])
    @admin_required
    def run_benchmark():
        """Run a benchmark test on an agent.

        Body: {agent_id, capability, test_prompt, expected_quality?}
        Sends test_prompt to agent's model via Ollama, measures performance.
        """
        data = request.get_json(force=True)
        agent_id = data.get("agent_id")
        capability = data.get("capability", "general")
        test_prompt = data.get("test_prompt", "")
        if not agent_id or not test_prompt:
            return jsonify({"error": "agent_id and test_prompt required"}), 400

        from services.agent_service import get_agent, update_skill_from_benchmark

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        model_name = agent.get("model", "")
        if not model_name:
            return jsonify({"error": "Agent has no model assigned"}), 400

        system_prompt = agent.get("system_prompt", "") or ""

        # Create benchmark run
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO action_benchmark_runs
                   (action_key, station_code, test_config, total_agents, status)
                   VALUES (%s, %s, %s, 1, 'running')
                   RETURNING id""",
                (
                    f"academy.benchmark.{capability}",
                    "ENGINEERING",
                    json.dumps(
                        {
                            "capability": capability,
                            "prompt": test_prompt[:500],
                            "agent_id": agent_id,
                        }
                    ),
                ),
            )
            run_id = cur.fetchone()["id"]

        # Call Ollama
        success = False
        duration_ms = 0
        response_text = ""
        error_msg = ""
        score = 0.0

        try:
            json.dumps(
                {
                    "model": model_name,
                    "prompt": test_prompt,
                    "system": system_prompt,
                    "stream": False,
                    "options": {
                        "temperature": float(agent.get("temperature", 0.7)),
                        "num_predict": int(agent.get("max_tokens", 2048)),
                    },
                }
            ).encode()

            from tools.department_hq.services.department_dispatcher import dispatch

            # NOTE: the old call passed model=model_name, which the canonical
            # signature silently dropped — benchmarks have been hitting
            # whatever the 'benchmark' capability routes to, not the target
            # model. Until prefer_model is added to the dispatcher (task
            # #2129), benchmarks rely on capability routing for the under-
            # test model. Pass target model via module_id for log traceability.
            start = time.time()
            result = dispatch(
                capability="benchmark",
                prompt=f"{system_prompt}\n\n{test_prompt}" if system_prompt else test_prompt,
                module_id=f"agent_academy:{model_name}",
                timeout=120,
            )
            duration_ms = int((time.time() - start) * 1000)

            response_text = result.response if result and result.success else ""
            prompt_tokens = getattr(result, "prompt_tokens", 0) or 0
            completion_tokens = getattr(result, "completion_tokens", 0) or 0
            success = bool(response_text.strip())

            # Basic quality scoring: length + speed + completeness
            length_score = min(1.0, len(response_text) / 500)  # reward up to 500 chars
            speed_score = max(0.0, 1.0 - (duration_ms / 30000))  # penalize >30s
            completeness = 1.0 if len(response_text) > 50 else 0.5
            score = round((length_score * 0.3 + speed_score * 0.3 + completeness * 0.4), 3)

        except Exception as e:
            error_msg = str(e)[:500]
            logger.warning("Benchmark failed for agent #%d: %s", agent_id, error_msg)
            prompt_tokens = 0
            completion_tokens = 0

        # Store result
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO action_benchmark_results
                   (run_id, agent_id, agent_name, display_name, model_used,
                    duration_ms, prompt_tokens, completion_tokens, total_tokens,
                    success, error_message, response_preview, score)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    run_id,
                    agent_id,
                    agent.get("name", ""),
                    agent.get("display_name", ""),
                    model_name,
                    duration_ms,
                    prompt_tokens,
                    completion_tokens,
                    prompt_tokens + completion_tokens,
                    success,
                    error_msg or None,
                    response_text[:1000],
                    score,
                ),
            )

            # Update run status
            status = "completed" if success else "failed"
            cur.execute(
                """UPDATE action_benchmark_runs
                   SET status = %s, completed_agents = %s, failed_agents = %s,
                       completed_at = NOW()
                   WHERE id = %s""",
                (
                    status,
                    1 if success else 0,
                    0 if success else 1,
                    run_id,
                ),
            )

        # Update agent skill level from score
        if success and score > 0:
            try:
                update_skill_from_benchmark(agent_id, capability, score)
            except Exception as e:
                logger.warning("Failed to update skill from benchmark: %s", e)

        return jsonify(
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "model": model_name,
                "success": success,
                "score": score,
                "duration_ms": duration_ms,
                "response_preview": response_text[:500],
                "error": error_msg or None,
            }
        )

    @bp.route("/api/benchmarks/rankings")
    @admin_required
    def rankings():
        """Agents ranked by capability scores."""
        capability = request.args.get("capability")
        with get_db_cursor() as (conn, cur):
            if capability:
                cur.execute(
                    """SELECT a.id AS agent_id, a.name, a.display_name, a.department,
                              a.model, s.skill_name, s.proficiency_level, s.skill_category
                       FROM agent_skills s
                       JOIN agents a ON a.id = s.agent_id
                       WHERE s.skill_name = %s AND a.status = 'active'
                       ORDER BY s.proficiency_level DESC, a.display_name""",
                    (capability,),
                )
            else:
                cur.execute(
                    """SELECT a.id AS agent_id, a.name, a.display_name, a.department,
                              a.model, s.skill_name, s.proficiency_level, s.skill_category
                       FROM agent_skills s
                       JOIN agents a ON a.id = s.agent_id
                       WHERE a.status = 'active'
                       ORDER BY s.skill_name, s.proficiency_level DESC"""
                )
            rows = [dict(r) for r in cur.fetchall()]

        # Group by capability
        capabilities = {}
        for row in rows:
            skill = row["skill_name"]
            if skill not in capabilities:
                capabilities[skill] = []
            capabilities[skill].append(row)

        return jsonify({"capabilities": capabilities, "total_skills": len(capabilities)})

    @bp.route("/api/ab-test/run", methods=["POST"])
    @admin_required
    def run_ab_test():
        """Run A/B test comparing two models.

        Body: {model_a, model_b, test_prompt, capability?}
        """
        data = request.get_json(force=True)
        model_a = data.get("model_a")
        model_b = data.get("model_b")
        test_prompt = data.get("test_prompt", "")
        capability = data.get("capability", "general")

        if not model_a or not model_b or not test_prompt:
            return jsonify({"error": "model_a, model_b, and test_prompt required"}), 400

        # --- Cloud Comparison Lane (#4661): branch off to the async approval
        # path when either side selects a cloud provider. Both-local falls
        # through unchanged to the existing synchronous path below.
        from tools.agent_academy.ab_compare import parse_model_selection, classify_run

        sel_a = parse_model_selection(model_a)
        sel_b = parse_model_selection(model_b)
        klass = classify_run(sel_a, sel_b)

        if klass["has_cloud"]:
            from tools.department_hq.services.department_dispatcher import get_dispatcher
            from ai_bridge.external_providers import weekly_budget_status
            from ai_bridge.agent_loop import request_approval

            disp = get_dispatcher()
            # 1. budget guard — refuse before enqueue if any cloud provider is over budget
            for pk in klass["cloud_providers"]:
                if not disp._cloud_budget_ok(pk, "ab_compare"):
                    st = weekly_budget_status(pk)
                    return Response(
                        json.dumps(
                            {
                                "status": "budget_exhausted",
                                "provider": pk,
                                "weekly_remaining": st.get("remaining"),
                            },
                            default=str,
                        ),
                        mimetype="application/json",
                    )

            # 2. enqueue pending_approval run
            # NOTE: action_benchmark_runs.station_code is NOT NULL (no default)
            # and started_by is INT (references a user id) — the original
            # design draft omitted station_code and put a string into
            # started_by, which would fail (NOT NULL violation / int cast
            # error). Fixed here against the live schema (migration 129):
            # station_code='ENGINEERING' matches the existing sync-path
            # convention below; started_by is left NULL (nullable, no int
            # user id available from this caller).
            test_config = {
                "type": "ab_compare",
                "capability": capability,
                "prompt": test_prompt,
                "model_a": model_a,
                "model_b": model_b,
                "sel_a": sel_a,
                "sel_b": sel_b,
                "cloud_providers": klass["cloud_providers"],
                "judge": True,
            }
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO action_benchmark_runs
                       (action_key, station_code, status, test_config, started_at)
                       VALUES (%s, 'ENGINEERING', 'pending_approval', %s, NOW())
                       RETURNING id""",
                    (f"academy.ab_test.{capability}", Json(test_config)),
                )
                run_id = cur.fetchone()["id"]

            # 3. ask-first Telegram approval (per-run; independent of global escalation_mode)
            approval_id = request_approval(
                action_type="cloud_comparison",
                action_data={
                    "run_id": run_id,
                    "prompt_preview": test_prompt[:200],
                    "cloud_providers": klass["cloud_providers"],
                    "model_a": model_a,
                    "model_b": model_b,
                },
                reason=f"A/B compare: {model_a} vs {model_b}",
                requested_by="ab_compare",
                tier=2,
            )

            # 3b. request_approval() returns None when it couldn't enqueue a
            # Telegram approval — most commonly the global per-action_type
            # dedup in _check_existing_approval() (cloud_comparison has no
            # per-run dedup key, so ANY second concurrent comparison collides
            # with an already-pending one). Returning a fake pending_approval
            # here would leave the UI polling forever with no Telegram message
            # to ever approve, until the worker's 24h expiry. Fail the run
            # honestly instead (#4661 review fix).
            if approval_id is None:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE action_benchmark_runs SET status = 'failed', completed_at = NOW(), "
                        "metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{cancelled_reason}', "
                        "%s::jsonb) WHERE id = %s",
                        (json.dumps("approval_unavailable"), run_id),
                    )
                return Response(
                    json.dumps(
                        {
                            "status": "approval_unavailable",
                            "run_id": run_id,
                            "message": (
                                "A cloud comparison is already awaiting your Telegram "
                                "approval — approve or deny that one first."
                            ),
                        },
                        default=str,
                    ),
                    mimetype="application/json",
                )

            # 4. link approval back onto the run for the worker
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE action_benchmark_runs SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), "
                    "'{approval_id}', %s::jsonb) WHERE id = %s",
                    (json.dumps(approval_id), run_id),
                )

            return Response(
                json.dumps(
                    {"status": "pending_approval", "run_id": run_id, "approval_id": approval_id},
                    default=str,
                ),
                mimetype="application/json",
            )

        # else: both-local -> fall through to the EXISTING synchronous path unchanged
        results = {}
        for label, model_name in [("a", model_a), ("b", model_b)]:
            try:
                from tools.department_hq.services.department_dispatcher import dispatch

                # #4707: actually run the SELECTED local model. model_override IS
                # honored by request_work (unlike the bare `model` kwarg, which the
                # canonical signature drops) — so each side runs its own model and the
                # judge compares two DIFFERENT models instead of one routed model vs
                # itself. model_override pins to the hub: fine for a controlled A/B
                # (both sides same node = fair). Timeout bumped for cold-loading
                # larger candidates (e.g. an 8B first-load).
                start = time.time()
                result = dispatch(
                    capability="benchmark",
                    prompt=test_prompt,
                    module_id=f"agent_academy:{model_name}",
                    model_override=model_name,
                    timeout=240,
                )
                duration_ms = int((time.time() - start) * 1000)

                results[label] = {
                    "model": model_name,
                    "response": result.response if result and result.success else "",
                    "duration_ms": duration_ms,
                    "prompt_tokens": getattr(result, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(result, "completion_tokens", 0) or 0,
                    "success": bool(result and result.success),
                    "error": None if (result and result.success) else getattr(result, "error", "dispatch failed"),
                }
            except Exception as e:
                results[label] = {
                    "model": model_name,
                    "response": "",
                    "duration_ms": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "success": False,
                    "error": str(e)[:500],
                }

        # #4718: run the LOCAL judge on the two answers so local-vs-local yields a real
        # verdict (score + winner + rationale) instead of the old hardcoded score=0.
        # Cloud runs already judge via the async worker; this brings the sync local path
        # to parity. Only judge when BOTH sides produced a response.
        verdict = {"score_a": None, "score_b": None, "winner": None, "rationale": ""}
        if results.get("a", {}).get("success") and results.get("b", {}).get("success"):
            try:
                from tools.department_hq.services.department_dispatcher import dispatch as _judge_dispatch
                from tools.agent_academy.ab_compare import build_judge_prompt, parse_judge_result

                _judge_model = "qwen2.5:7b"
                _jr = _judge_dispatch(
                    capability="benchmark",
                    prompt=build_judge_prompt(test_prompt, results["a"]["response"], results["b"]["response"]),
                    module_id="agent_academy:judge",
                    model_override=_judge_model,
                    timeout=180,
                )
                if _jr and _jr.success:
                    verdict = parse_judge_result(_jr.response)
                    verdict["judge_model"] = _judge_model
            except Exception as _je:
                logger.warning("ab_test judge failed: %s", _je)
        _score_for = {"a": verdict.get("score_a"), "b": verdict.get("score_b")}

        # Store A/B test in benchmark runs
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO action_benchmark_runs
                   (action_key, station_code, test_config, total_agents, completed_agents,
                    failed_agents, status, completed_at)
                   VALUES (%s, 'ENGINEERING', %s, 2, %s, %s, 'completed', NOW())
                   RETURNING id""",
                (
                    f"academy.ab_test.{capability}",
                    json.dumps(
                        {
                            "type": "ab_test",
                            "capability": capability,
                            "prompt": test_prompt[:500],
                            "model_a": model_a,
                            "model_b": model_b,
                            "verdict": verdict,
                        }
                    ),
                    sum(1 for r in results.values() if r["success"]),
                    sum(1 for r in results.values() if not r["success"]),
                ),
            )
            run_id = cur.fetchone()["id"]

            # Store individual results
            for label, r in results.items():
                cur.execute(
                    """INSERT INTO action_benchmark_results
                       (run_id, agent_id, agent_name, display_name, model_used,
                        duration_ms, prompt_tokens, completion_tokens, total_tokens,
                        success, error_message, response_preview, score)
                       VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        run_id,
                        f"model_{label}",
                        r["model"],
                        r["model"],
                        r["duration_ms"],
                        r["prompt_tokens"],
                        r["completion_tokens"],
                        r["prompt_tokens"] + r["completion_tokens"],
                        r["success"],
                        r["error"],
                        r["response"][:1000],
                        _score_for.get(label),
                    ),
                )

        return jsonify(
            {
                "run_id": run_id,
                "capability": capability,
                "results": results,
                "verdict": verdict,
            }
        )

    @bp.route("/api/ab-test/run/<int:run_id>", methods=["GET"])
    @admin_required
    def ab_test_run_status(run_id):
        """Poll status of an A/B test run — cloud pending_approval, running, or completed."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, test_config, metadata FROM action_benchmark_runs WHERE id = %s",
                (run_id,),
            )
            run = cur.fetchone()
            if not run:
                return Response(json.dumps({"error": "not found"}), status=404, mimetype="application/json")

            cur.execute(
                """SELECT agent_name, model_used, provider, duration_ms,
                          prompt_tokens, completion_tokens, total_tokens, success,
                          error_message, response_preview, score, rank
                   FROM action_benchmark_results
                   WHERE run_id = %s
                   ORDER BY agent_name""",
                (run_id,),
            )
            rows = cur.fetchall()

        # Remap raw DB columns to the field names renderABResults() (agent-academy.js)
        # actually reads — the same shape the synchronous both-local path in
        # run_ab_test() already returns. Without this remap a completed cloud
        # comparison renders blank (#4661 final-review Critical fix): the raw
        # columns are model_used/response_preview/error_message/total_tokens,
        # but the frontend reads model/response/error/prompt_tokens+completion_tokens.
        results = {}
        for r in rows:
            side = "a" if r["agent_name"] == "model_a" else "b"
            results[side] = {
                "model": r["model_used"],
                "response": r["response_preview"],
                "prompt_tokens": r["prompt_tokens"] or 0,
                "completion_tokens": r["completion_tokens"] or 0,
                "success": r["success"],
                "error": r["error_message"],
                "duration_ms": r["duration_ms"],
                "provider": r["provider"],
                "score": r["score"],
                "rank": r["rank"],
            }

        meta = run["metadata"] or {}
        return Response(
            json.dumps(
                {
                    "status": run["status"],
                    "results": results or None,
                    "judge": meta.get("judge_result"),
                    "cancelled_reason": meta.get("cancelled_reason"),
                },
                default=str,
            ),
            mimetype="application/json",
        )

    @bp.route("/api/benchmarks/summary")
    @admin_required
    def benchmark_summary():
        """Summary of benchmark results by skill category with best models."""
        from tools.agent_academy.services.benchmark_service import get_benchmark_summary

        return jsonify({"success": True, **get_benchmark_summary()})

    @bp.route("/api/benchmarks/update-roster", methods=["POST"])
    @admin_required
    def benchmark_update_roster():
        """Update agent model assignments based on benchmark results.

        Body: {dry_run: true} (default true for safety)
        """
        from tools.agent_academy.services.benchmark_service import update_roster_models

        data = request.get_json(force=True) if request.is_json else {}
        dry_run = data.get("dry_run", True)
        changes = update_roster_models(dry_run=dry_run)
        return jsonify({"success": True, "dry_run": dry_run, "changes": changes})

    @bp.route("/api/ab-test/history")
    @admin_required
    def ab_test_history():
        """Recent A/B test results."""
        limit = request.args.get("limit", 10, type=int)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT r.id, r.test_config, r.started_at, r.completed_at
                   FROM action_benchmark_runs r
                   WHERE r.action_key LIKE 'academy.ab_test.%%'
                   ORDER BY r.started_at DESC
                   LIMIT %s""",
                (limit,),
            )
            runs = []
            for row in cur.fetchall():
                run = dict(row)
                run["started_at"] = str(run["started_at"]) if run["started_at"] else None
                run["completed_at"] = str(run["completed_at"]) if run["completed_at"] else None
                run["test_config"] = run["test_config"] or {}

                cur.execute(
                    """SELECT agent_name, display_name AS model, model_used,
                              duration_ms, success, response_preview,
                              prompt_tokens, completion_tokens
                       FROM action_benchmark_results
                       WHERE run_id = %s
                       ORDER BY agent_name""",
                    (run["id"],),
                )
                run["results"] = [dict(r) for r in cur.fetchall()]
                runs.append(run)

        return jsonify({"tests": runs})

    @bp.route("/api/ab-test/models", methods=["GET"])
    @admin_required
    def ab_test_models():
        """Local + cloud model lists for A/B testing, with weekly budget headroom."""
        try:
            from tools.department_hq.fleet_helpers import (
                get_ollama_models,
                OLLAMA_LOCAL_HOST,
                OLLAMA_DEFAULT_PORT,
            )

            local = [{"name": m} for m in get_ollama_models(OLLAMA_LOCAL_HOST, int(OLLAMA_DEFAULT_PORT))]
        except Exception:
            local = []

        cloud = []
        try:
            from ai_bridge.external_providers import weekly_budget_status

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT provider_key, display_name, default_model, is_cloud_proxy, tier_position "
                    "FROM contractor_providers WHERE capabilities ? 'text_chat' AND is_active = true "
                    "ORDER BY display_name"
                )
                rows = cur.fetchall()
            for r in rows:
                pk = r["provider_key"]
                free_tier = bool(r["tier_position"] and r["tier_position"] >= 8 and not r["is_cloud_proxy"])
                try:
                    status = weekly_budget_status(pk)
                    weekly_remaining = status.get("remaining")
                    disabled = bool(status.get("over_budget"))
                except Exception as budget_err:
                    # Advisory only — the real spend guard is _cloud_budget_ok at
                    # dispatch time. A per-provider hiccup here must not drop the
                    # provider from the list (nor drop the rest of the loop).
                    logger.warning("ab_test_models budget lookup failed for %s: %s", pk, budget_err)
                    weekly_remaining = None
                    disabled = False
                cloud.append(
                    {
                        "provider_key": pk,
                        "display_name": r["display_name"],
                        "model": r["default_model"],
                        "free_tier": free_tier,
                        "weekly_remaining": weekly_remaining,
                        "disabled": disabled,
                    }
                )
        except Exception as e:
            logger.warning("ab_test_models cloud enumerate failed: %s", e)

        return Response(json.dumps({"local": local, "cloud": cloud}, default=str), mimetype="application/json")
