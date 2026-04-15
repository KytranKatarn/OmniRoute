"""
Agent Academy — Benchmark Routes

Run benchmarks, view results, rank agents by capability.
"""

import json
import logging
import time

from flask import jsonify, request
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
            payload = json.dumps(
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

            from bridge_dispatcher import dispatch

            start = time.time()
            result = dispatch(
                capability="benchmark",
                prompt=f"{system_prompt}\n\n{test_prompt}" if system_prompt else test_prompt,
                model=model_name,
                module_id="agent_academy",
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

        results = {}
        for label, model_name in [("a", model_a), ("b", model_b)]:
            try:
                from bridge_dispatcher import dispatch

                start = time.time()
                result = dispatch(
                    capability="benchmark",
                    prompt=test_prompt,
                    model=model_name,
                    module_id="agent_academy",
                    timeout=120,
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
                       VALUES (%s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)""",
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
                    ),
                )

        return jsonify(
            {
                "run_id": run_id,
                "capability": capability,
                "results": results,
            }
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
