"""Benchmark Service — Agent performance testing for station actions.

Runs a standardized test prompt against all eligible agents for a given
action, records timing/token metrics, and produces a ranked leaderboard.

Part of Project #110: Agent Action Benchmarks.
"""

import logging
import threading
import time
from typing import Dict, List, Optional

from database import get_db_connection
from services.department_coordinator import get_coordinator as get_dept_coordinator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bridge dispatcher (all AI work routes through here)
# ---------------------------------------------------------------------------
try:
    from tools.department_hq.services.bridge_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
    BRIDGE_AVAILABLE = True
except Exception:
    _dispatcher = None
    BRIDGE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Startup: mark any stale "running" benchmarks as failed (e.g. after restart)
# ---------------------------------------------------------------------------
try:
    with get_db_connection() as _conn:
        _cur = _conn.cursor()
        _cur.execute(
            "UPDATE action_benchmark_runs SET status = 'failed', " "completed_at = NOW() WHERE status = 'running'"
        )
        if _cur.rowcount:
            logger.info(
                "Benchmark startup: marked %d stale running benchmarks as failed",
                _cur.rowcount,
            )
        _cur.close()
        _conn.commit()
except Exception as _e:
    logger.warning("Benchmark startup cleanup failed: %s", _e)


# ---------------------------------------------------------------------------
# Eligible agent discovery
# Models that cannot generate text (embedding-only, non-chat architectures)
EMBEDDING_ONLY_MODELS = frozenset(
    {
        "arctic-embed-cpu",
        "arctic-embed-cpu:latest",
        "nomic-embed-text",
        "nomic-embed-text:latest",
    }
)


# ---------------------------------------------------------------------------
def get_eligible_agents(capability: str) -> List[Dict]:
    """Return all agents that can handle *capability* (score > 0).

    Queries the dispatcher's cached agent roster and scores each one.
    Excludes agents whose models are embedding-only (can't generate text).
    Returns list of ``{id, name, display_name, station_code, model}``
    sorted by score descending.
    """
    if not BRIDGE_AVAILABLE or not _dispatcher:
        return []

    _dispatcher._refresh_agent_cache()
    _dispatcher._refresh_welfare_cache()

    eligible = []
    for name, info in _dispatcher._agent_cache.items():
        model = info.get("model", "")
        if model in EMBEDDING_ONLY_MODELS:
            logger.debug("Skipping %s — embedding-only model %s", name, model)
            continue

        department = info.get("department", "")
        score, block_reason = get_dept_coordinator().score_agent(name, info, capability, department)
        if score > 0:
            eligible.append(
                {
                    "id": info.get("id"),
                    "name": name,
                    "display_name": info.get("display_name", name),
                    "station_code": info.get("station_code", ""),
                    "model": model,
                    "score": score,
                }
            )

    eligible.sort(key=lambda a: a["score"], reverse=True)
    return eligible


# ---------------------------------------------------------------------------
# Start a benchmark run
# ---------------------------------------------------------------------------
def start_benchmark(action_key: str, user_id: Optional[int] = None, include_contractors: bool = False) -> Dict:
    """Kick off a benchmark run for *action_key*.

    1. Load test_config from station_actions.
    2. Find eligible agents for the action's capability.
    3. Create a benchmark run row + bridge_jobs row.
    4. Spawn a background thread that tests each agent sequentially.

    Returns ``{success, run_id, job_id, total_agents}`` or error dict.
    """
    if not BRIDGE_AVAILABLE or not _dispatcher:
        return {"success": False, "error": "Bridge dispatcher unavailable"}

    # 0. Guard: only one benchmark at a time
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, action_key FROM action_benchmark_runs " "WHERE status = 'running' LIMIT 1")
            running = cur.fetchone()
            if running:
                rk = running[1] if not isinstance(running, dict) else running["action_key"]
                return {
                    "success": False,
                    "error": f"A benchmark is already running ({rk}). Wait for it to finish.",
                }
    except Exception:
        pass  # non-critical — proceed with the start

    # 1. Load action + test_config
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT action_key, station_code, label, test_config
                FROM station_actions
                WHERE action_key = %s AND is_active = TRUE
                """,
                (action_key,),
            )
            row = cur.fetchone()
    except Exception as e:
        return {"success": False, "error": f"DB error: {e}"}

    if not row:
        return {"success": False, "error": f"Action '{action_key}' not found"}

    # Handle both dict-cursor and tuple-cursor results
    if isinstance(row, dict):
        action = row
    else:
        action = {
            "action_key": row[0],
            "station_code": row[1],
            "label": row[2],
            "test_config": row[3],
        }

    test_config = action.get("test_config")
    if not test_config:
        return {
            "success": False,
            "error": f"No test_config for action '{action_key}'",
        }
    # Inject runtime setting from CTRL panel
    if include_contractors:
        test_config["include_contractors"] = True
    capability = test_config.get("capability", "general")
    benchmark_type = test_config.get("benchmark_type", "llm")

    # 2. Find eligible agents (or prompts for image benchmarks)
    if benchmark_type == "image":
        prompts = test_config.get("prompts", [])
        if not prompts:
            return {"success": False, "error": "No prompts in image benchmark test_config"}
        # Count contractors if enabled
        contractor_count = 0
        if test_config.get("include_contractors"):
            contractor_count = len(_discover_image_contractors())
        total_items = len(prompts) + (contractor_count * len(prompts))
    else:
        agents = get_eligible_agents(capability)
        if not agents:
            return {
                "success": False,
                "error": f"No eligible agents for capability '{capability}'",
            }
        total_items = len(agents)

    # 3. Create benchmark run
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO action_benchmark_runs
                    (action_key, station_code, test_config,
                     total_agents, started_by)
                VALUES (%s, %s, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (
                    action["action_key"],
                    action["station_code"],
                    __import__("json").dumps(test_config),
                    total_items,
                    user_id,
                ),
            )
            run_id = cur.fetchone()[0]
            conn.commit()
    except Exception as e:
        return {"success": False, "error": f"Failed to create run: {e}"}

    # 4. Launch background thread
    if benchmark_type == "image":
        thread = threading.Thread(
            target=_run_image_benchmark_thread,
            args=(run_id, action, test_config),
            daemon=True,
        )
    else:
        thread = threading.Thread(
            target=_run_benchmark_thread,
            args=(run_id, None, action, agents, test_config),
            daemon=True,
        )
    thread.start()

    return {
        "success": True,
        "run_id": run_id,
        "job_id": None,
        "total_agents": total_items,
    }


# ---------------------------------------------------------------------------
# Background benchmark execution
# ---------------------------------------------------------------------------
def _run_benchmark_thread(
    run_id: int,
    job_id: Optional[int],
    action: Dict,
    agents: List[Dict],
    test_config: Dict,
):
    """Test each agent sequentially and record results.

    Uses a single DB connection for all writes to avoid exhausting the
    connection pool (the dispatcher opens its own connections per call).
    """
    import json as _json
    import psycopg2

    capability = test_config.get("capability", "general")
    prompt = test_config.get("prompt", "Hello")
    system_prompt = test_config.get("system_prompt")

    completed = 0
    failed = 0
    results = []

    # Open ONE connection for the entire benchmark thread
    try:
        db_conn = psycopg2.connect(
            host=__import__("os").getenv("DB_HOST", "192.168.1.200"),
            port=__import__("os").getenv("DB_PORT", "5432"),
            database=__import__("os").getenv("DB_NAME", "archie"),
            user=__import__("os").getenv("DB_USER", "archie"),
            password=__import__("database")._get_db_password(),
        )
        db_conn.autocommit = True
    except Exception as e:
        logger.error("Benchmark thread %d: can't connect to DB: %s", run_id, e)
        return

    # Pre-warm unique models so cold-start doesn't skew timing
    unique_models = list({a.get("model", "") for a in agents if a.get("model")})
    if unique_models:
        import requests as _req

        ollama_host = __import__("os").getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        for model in unique_models:
            try:
                _req.post(
                    f"{ollama_host}/api/generate",
                    json={"model": model, "prompt": "hi", "options": {"num_predict": 1}},
                    timeout=120,
                )
                logger.debug("Benchmark: pre-warmed model %s", model)
            except Exception as e:
                logger.debug("Benchmark: warm-up failed for %s: %s", model, e)

    try:
        for agent in agents:
            agent_name = agent["name"]
            agent_id = agent["id"]
            display_name = agent.get("display_name", agent_name)

            try:
                # Ensure agent cache is fresh so prefer_agent can find the agent
                if _dispatcher:
                    _dispatcher._busy_agents.discard(agent_name)
                    # Keep cache alive — benchmark may outlast the 5-min TTL
                    if agent_name not in _dispatcher._agent_cache:
                        _dispatcher._refresh_agent_cache()

                result = _dispatcher.request_work(
                    capability=capability,
                    prompt=prompt,
                    module_id="benchmark",
                    system_prompt=system_prompt,
                    prefer_agent=agent_name,
                    user_id=None,
                    priority="low",
                    timeout=300,
                )

                # Verify the right agent was dispatched
                actual_agent = getattr(result, "agent_name", None)
                if actual_agent and actual_agent != agent_name:
                    logger.warning(
                        "Benchmark: wanted %s but got %s — recording as mismatch",
                        agent_name,
                        actual_agent,
                    )

                success = result.success
                duration_ms = result.duration_ms
                prompt_tokens = result.prompt_tokens
                completion_tokens = result.completion_tokens
                total_tokens = prompt_tokens + completion_tokens
                model_used = result.model_used
                provider = result.provider
                error_msg = result.error if not success else None
                response_preview = (result.response[:2000]) if result.response else None

            except Exception as e:
                logger.warning("Benchmark agent %s failed: %s", agent_name, e)
                success = False
                duration_ms = 0
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                model_used = agent.get("model", "unknown")
                provider = "ollama"
                error_msg = str(e)
                response_preview = None

            # Insert result
            try:
                cur = db_conn.cursor()
                cur.execute(
                    """
                    INSERT INTO action_benchmark_results
                        (run_id, agent_id, agent_name, display_name,
                         model_used, provider, duration_ms,
                         prompt_tokens, completion_tokens, total_tokens,
                         success, error_message, response_preview)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s)
                    """,
                    (
                        run_id,
                        agent_id,
                        agent_name,
                        display_name,
                        model_used,
                        provider,
                        duration_ms,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        success,
                        error_msg,
                        response_preview,
                    ),
                )
                cur.close()
            except Exception as e:
                logger.error("Failed to insert benchmark result: %s", e)

            if success:
                completed += 1
            else:
                failed += 1

            results.append(
                {
                    "agent_name": agent_name,
                    "success": success,
                    "duration_ms": duration_ms,
                    "total_tokens": total_tokens,
                    "response_preview": response_preview,
                }
            )

            # Update bridge job progress
            if job_id and _dispatcher:
                _dispatcher.update_job_progress(
                    job_id,
                    completed_steps=completed + failed,
                    failed_steps=failed,
                )

            # Update benchmark run progress
            try:
                cur = db_conn.cursor()
                cur.execute(
                    """
                    UPDATE action_benchmark_runs
                    SET completed_agents = %s, failed_agents = %s
                    WHERE id = %s
                    """,
                    (completed, failed, run_id),
                )
                cur.close()
            except Exception:
                pass

        # -------------------------------------------------------------------
        # Compute scores and ranks (use thread's own connection)
        # -------------------------------------------------------------------
        _compute_scores(run_id, results, conn=db_conn)

        # -------------------------------------------------------------------
        # Sync benchmark scores → agent_skills proficiency levels
        # -------------------------------------------------------------------
        try:
            sync_skills_from_benchmark(run_id, conn=db_conn)
        except Exception as e:
            logger.warning("Skill sync failed for run %d: %s", run_id, e)

        # -------------------------------------------------------------------
        # Auto-generate station recommendations after benchmark
        # -------------------------------------------------------------------
        try:
            generate_station_recommendations(action.get("station_code"))
        except Exception as e:
            logger.warning("Recommendation gen failed for run %d: %s", run_id, e)

        # Mark run complete
        final_status = "completed" if completed > 0 else "failed"
        try:
            cur = db_conn.cursor()
            cur.execute(
                """
                UPDATE action_benchmark_runs
                SET status = %s,
                    completed_agents = %s,
                    failed_agents = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (final_status, completed, failed, run_id),
            )
            cur.close()
        except Exception as e:
            logger.error("Failed to finalize benchmark run %d: %s", run_id, e)

        # Complete bridge job
        if job_id and _dispatcher:
            _dispatcher.complete_job(job_id, status="auto")

        logger.info(
            "Benchmark run %d complete: %d/%d agents succeeded",
            run_id,
            completed,
            len(agents),
        )

    finally:
        try:
            db_conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Image generation benchmark
# ---------------------------------------------------------------------------
def _run_image_benchmark_thread(
    run_id: int,
    action: Dict,
    test_config: Dict,
):
    """Test image generation across prompts/models via local + external contractors.

    Each prompt in test_config["prompts"] is generated and timed.
    When include_contractors is true, also tests configured external providers
    (Gemini Imagen, OpenAI DALL-E) for each prompt.
    Results are recorded as benchmark_results rows with the model as
    "agent_name" (since image gen doesn't use LLM agents).
    """
    import json as _json
    import psycopg2
    import time

    prompts = test_config.get("prompts", [])
    default_width = test_config.get("width", 512)
    default_height = test_config.get("height", 512)
    default_steps = test_config.get("steps", 15)
    include_contractors = test_config.get("include_contractors", False)

    # Find Pixel (image gen agent) for the agent_id field
    pixel_id = None
    pixel_display = "OllamaDiffuser"
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, display_name FROM agents WHERE name = 'Pixel' AND status = 'active'")
            row = cur.fetchone()
            if row:
                pixel_id = row[0] if isinstance(row, tuple) else row["id"]
                pixel_display = row[1] if isinstance(row, tuple) else row["display_name"]
    except Exception:
        pass

    # Build list of external contractor adapters to test
    contractor_tests = []
    if include_contractors:
        contractor_tests = _discover_image_contractors()

    completed = 0
    failed = 0
    results = []

    # Total items = local prompts + (contractor count × prompts)
    total_items = len(prompts) + (len(contractor_tests) * len(prompts))

    try:
        db_conn = psycopg2.connect(
            host=__import__("os").getenv("DB_HOST", "192.168.1.200"),
            port=__import__("os").getenv("DB_PORT", "5432"),
            database=__import__("os").getenv("DB_NAME", "archie"),
            user=__import__("os").getenv("DB_USER", "archie"),
            password=__import__("database")._get_db_password(),
        )
        db_conn.autocommit = True
    except Exception as e:
        logger.error("Image benchmark thread %d: can't connect to DB: %s", run_id, e)
        return

    # Update total_agents to include contractors
    if total_items != len(prompts):
        try:
            cur = db_conn.cursor()
            cur.execute(
                "UPDATE action_benchmark_runs SET total_agents = %s WHERE id = %s",
                (total_items, run_id),
            )
            cur.close()
        except Exception:
            pass

    def _insert_result(db, run, agent_id, agent_name, display, model, provider, dur, fsize, ok, err, preview):
        try:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO action_benchmark_results
                    (run_id, agent_id, agent_name, display_name,
                     model_used, provider, duration_ms,
                     prompt_tokens, completion_tokens, total_tokens,
                     success, error_message, response_preview)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s)
                """,
                (run, agent_id, agent_name, display, model, provider, dur, 0, 0, fsize, ok, err, preview),
            )
            cur.close()
        except Exception as e:
            logger.error("Failed to insert image benchmark result: %s", e)

    def _update_progress(db, run, comp, fail):
        try:
            cur = db.cursor()
            cur.execute(
                "UPDATE action_benchmark_runs SET completed_agents = %s, failed_agents = %s WHERE id = %s",
                (comp, fail, run),
            )
            cur.close()
        except Exception:
            pass

    try:
        # ── Phase 1: ComfyUI local tests via Bridge dispatcher ──
        # Route through dispatcher for proper bridge_job tracking, VRAM management,
        # and agent welfare integration (ADR-013: all inference through Bridge).
        from ai_bridge.comfyui_service import get_comfyui_service
        from tools.department_hq.services.bridge_dispatcher import BridgeDispatcher

        comfyui = get_comfyui_service()
        dispatcher = BridgeDispatcher()

        if not comfyui.health_check():
            logger.warning("Image benchmark %d: ComfyUI not available", run_id)
        else:
            comfy_models = comfyui.get_models().get("installed", [])
            if not comfy_models:
                logger.warning("Image benchmark %d: ComfyUI has no models installed", run_id)
            else:
                logger.info(
                    "Image benchmark %d: testing %d ComfyUI models × %d prompts (via dispatcher)",
                    run_id,
                    len(comfy_models),
                    len(prompts),
                )
                # Update total count (models × prompts)
                total_items = len(comfy_models) * len(prompts)
                try:
                    cur = db_conn.cursor()
                    cur.execute(
                        "UPDATE action_benchmark_runs SET total_agents = %s WHERE id = %s",
                        (total_items + (len(contractor_tests) * len(prompts)), run_id),
                    )
                    cur.close()
                except Exception:
                    pass

                for ckpt in comfy_models:
                    for i, prompt_cfg in enumerate(prompts):
                        prompt_text = prompt_cfg.get("prompt", "a cat")
                        category = prompt_cfg.get("category", f"test_{i}")
                        width = prompt_cfg.get("width", default_width)
                        height = prompt_cfg.get("height", default_height)
                        steps = prompt_cfg.get("steps", default_steps)

                        short_model = ckpt.replace(".safetensors", "").replace(".ckpt", "")
                        # SDXL models need 1024x1024 native resolution
                        if "xl" in ckpt.lower():
                            width, height = 1024, 1024
                        agent_label = f"{short_model} ({category})"
                        logger.info(
                            "Image benchmark %d: ComfyUI %s — %s",
                            run_id,
                            short_model,
                            prompt_text[:60],
                        )

                        try:
                            start_ms = int(time.time() * 1000)
                            result = dispatcher.request_work(
                                capability="image_generation",
                                prompt=prompt_text,
                                module_id="benchmark",
                                prefer_agent="Pixel",
                                context={
                                    "image_model": ckpt,
                                    "width": width,
                                    "height": height,
                                    "steps": steps,
                                },
                            )
                            duration_ms = int(time.time() * 1000) - start_ms

                            success = result.success
                            error_msg = result.error if not success else None
                            file_size = 0
                            file_path = ""
                            if success and result.metadata:
                                file_size = result.metadata.get("file_size_bytes", 0)
                                file_path = result.metadata.get("file_path", "")

                            if success:
                                response_preview = (
                                    f"Category: {category}\n"
                                    f"Model: {short_model}\n"
                                    f"Provider: ComfyUI (via dispatcher)\n"
                                    f"Agent: {result.agent_name or 'Pixel'}\n"
                                    f"Prompt: {prompt_text}\n"
                                    f"Size: {width}x{height}, Steps: {steps}\n"
                                    f"File: {file_path} ({file_size} bytes)\n"
                                    f"Duration: {duration_ms}ms ({duration_ms / 1000:.1f}s)"
                                )
                            else:
                                response_preview = f"FAILED: {error_msg}"
                        except Exception as e:
                            logger.warning("ComfyUI benchmark %s prompt %d failed: %s", ckpt, i, e)
                            success = False
                            duration_ms = 0
                            error_msg = str(e)
                            response_preview = f"EXCEPTION: {e}"
                            file_size = 0

                        _insert_result(
                            db_conn,
                            run_id,
                            pixel_id,
                            agent_label,
                            "ComfyUI",
                            short_model,
                            "comfyui",
                            duration_ms,
                            file_size,
                            success,
                            error_msg,
                            response_preview,
                        )

                        if success:
                            completed += 1
                        else:
                            failed += 1

                        results.append(
                            {
                                "agent_name": agent_label,
                                "success": success,
                                "duration_ms": duration_ms,
                                "total_tokens": file_size,
                                "response_preview": response_preview,
                            }
                        )
                        _update_progress(db_conn, run_id, completed, failed)

        # ── Phase 2: External contractor tests ──
        if contractor_tests:
            logger.info(
                "Image benchmark %d: testing %d external contractors",
                run_id,
                len(contractor_tests),
            )

        for contractor in contractor_tests:
            c_key = contractor["provider_key"]
            c_name = contractor["display_name"]
            c_model = contractor["model"]
            c_adapter = contractor["adapter"]

            for i, prompt_cfg in enumerate(prompts):
                prompt_text = prompt_cfg.get("prompt", "a cat")
                category = prompt_cfg.get("category", f"test_{i}")

                agent_label = f"{c_model} ({category})"
                logger.info(
                    "Image benchmark %d: contractor %s — %s",
                    run_id,
                    c_key,
                    prompt_text[:60],
                )

                try:
                    import time

                    start_ms = int(time.time() * 1000)
                    result = c_adapter(
                        {
                            "type": "image",
                            "prompt": prompt_text,
                            "params": contractor.get("params", {}),
                        }
                    )
                    duration_ms = int(time.time() * 1000) - start_ms

                    success = result.get("success", False)
                    error_msg = result.get("error") if not success else None
                    meta = result.get("metadata", {})
                    file_size = meta.get("file_size_bytes", 0) if success else 0
                    file_path = result.get("file_path", "")
                    cost_usd = meta.get("cost_usd", 0.0)

                    if success:
                        response_preview = (
                            f"Category: {category}\n"
                            f"Model: {c_model}\n"
                            f"Provider: {c_name}\n"
                            f"Prompt: {prompt_text}\n"
                            f"File: {file_path} ({file_size} bytes)\n"
                            f"Cost: ${cost_usd:.4f}\n"
                            f"Duration: {duration_ms}ms ({duration_ms / 1000:.1f}s)"
                        )
                    else:
                        response_preview = f"FAILED: {error_msg}"

                except Exception as e:
                    logger.warning(
                        "Image benchmark contractor %s prompt %d failed: %s",
                        c_key,
                        i,
                        e,
                    )
                    success = False
                    duration_ms = 0
                    error_msg = str(e)
                    response_preview = f"EXCEPTION: {e}"
                    file_size = 0

                _insert_result(
                    db_conn,
                    run_id,
                    pixel_id,
                    agent_label,
                    c_name,
                    c_model,
                    c_key,
                    duration_ms,
                    file_size,
                    success,
                    error_msg,
                    response_preview,
                )

                if success:
                    completed += 1
                else:
                    failed += 1

                results.append(
                    {
                        "agent_name": agent_label,
                        "success": success,
                        "duration_ms": duration_ms,
                        "total_tokens": file_size,
                        "response_preview": response_preview,
                    }
                )
                _update_progress(db_conn, run_id, completed, failed)

        # Compute scores — for image gen, score based on success + speed
        _compute_image_scores(run_id, results, conn=db_conn)

        # Mark run complete
        final_status = "completed" if completed > 0 else "failed"
        try:
            cur = db_conn.cursor()
            cur.execute(
                """
                UPDATE action_benchmark_runs
                SET status = %s, completed_agents = %s,
                    failed_agents = %s, completed_at = NOW()
                WHERE id = %s
                """,
                (final_status, completed, failed, run_id),
            )
            cur.close()
        except Exception as e:
            logger.error("Failed to finalize image benchmark %d: %s", run_id, e)

        logger.info(
            "Image benchmark %d complete: %d/%d items succeeded",
            run_id,
            completed,
            total_items,
        )

    finally:
        try:
            db_conn.close()
        except Exception:
            pass


def _discover_image_contractors() -> list:
    """Find external contractor providers that support image generation.

    Checks contractor_providers table for providers with image_gen capability,
    verifies their API key is configured, and returns adapter functions.
    """
    contractors = []

    # Map provider_key → adapter function
    try:
        from ai_bridge.external_providers import (
            _gemini_media_adapter,
            _openai_image_adapter,
        )
    except ImportError:
        logger.warning("Could not import external provider adapters")
        return []

    adapter_map = {
        "gemini": {
            "adapter": _gemini_media_adapter,
            "env_var": "GEMINI_API_KEY",
            "model": "imagen-3.0-generate-002",
            "params": {"aspect_ratio": "1:1"},
        },
        "openai": {
            "adapter": _openai_image_adapter,
            "env_var": "OPENAI_API_KEY",
            "model": "dall-e-3",
            "params": {"size": "1024x1024", "quality": "standard"},
        },
    }

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT provider_key, display_name, default_model, is_active
                FROM contractor_providers
                WHERE capabilities::text ILIKE '%%image%%'
                  AND is_active = TRUE
                  AND provider_key NOT IN ('ollama_diffuser', 'comfyui')
                """
            )
            rows = cur.fetchall()
            for row in rows:
                pk = row[0] if isinstance(row, tuple) else row["provider_key"]
                dn = row[1] if isinstance(row, tuple) else row["display_name"]

                if pk not in adapter_map:
                    continue

                info = adapter_map[pk]
                # Check if API key is configured
                api_key = __import__("os").environ.get(info["env_var"], "")
                if not api_key:
                    logger.info("Skipping contractor %s: no API key (%s)", pk, info["env_var"])
                    continue

                contractors.append(
                    {
                        "provider_key": pk,
                        "display_name": dn,
                        "model": info["model"],
                        "adapter": info["adapter"],
                        "params": info["params"],
                    }
                )
                logger.info("Image benchmark: including contractor %s (%s)", pk, dn)
    except Exception as e:
        logger.error("Failed to discover image contractors: %s", e)

    return contractors


def _compute_image_scores(run_id: int, results: List[Dict], conn=None):
    """Score image benchmark results.

    Formula: score = (success * 40) + (speed_norm * 30) + (size_norm * 30)
    - success: 40 points for generating an image
    - speed_norm: faster = higher (relative to slowest in run)
    - size_norm: larger file = more detail (relative to largest)
    """
    successful = [r for r in results if r["success"]]
    if not successful:
        return

    max_duration = max(r["duration_ms"] for r in successful) or 1
    max_size = max(r["total_tokens"] for r in successful) or 1  # total_tokens = file_size

    scores = {}
    for r in results:
        if r["success"]:
            speed_norm = 1.0 - (r["duration_ms"] / max_duration)
            size_norm = r["total_tokens"] / max_size
            score = 40.0 + (speed_norm * 30.0) + (size_norm * 30.0)
        else:
            score = 0.0
        scores[r["agent_name"]] = round(score, 1)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _write(c):
        cur = c.cursor()
        for rank, (agent_name, score) in enumerate(ranked, 1):
            cur.execute(
                """
                UPDATE action_benchmark_results
                SET score = %s, rank = %s
                WHERE run_id = %s AND agent_name = %s
                """,
                (score, rank, run_id, agent_name),
            )
        cur.close()

    try:
        if conn:
            _write(conn)
        else:
            with get_db_connection() as pool_conn:
                _write(pool_conn)
                pool_conn.commit()
    except Exception as e:
        logger.error("Failed to update image scores for run %d: %s", run_id, e)


def _compute_scores(run_id: int, results: List[Dict], conn=None):
    """Compute normalized scores and assign ranks.

    Formula: score = (success * 50) + (speed_norm * 10) + (quality_norm * 40)

    Quality is rank-based: responses are ranked by length adequacy (not too
    short, not excessively long).  Speed is a minor factor — it matters for
    tie-breaking but shouldn't dominate.

    Normalization is relative to the run:
    - speed_norm  = 1 - (duration / max_duration)   [faster = higher, 10% weight]
    - quality_norm = rank-based from response length [0-1, 40% weight]
      Responses between 50-500 chars score highest; too short (<30) or
      excessively long (>2000) are penalized.

    If *conn* is provided, uses it directly (no pool checkout).
    """
    successful = [r for r in results if r["success"]]
    if not successful:
        return

    max_duration = max(r["duration_ms"] for r in successful) or 1

    def _response_quality(r):
        """Score response quality 0-1 based on length adequacy."""
        preview = r.get("response_preview") or ""
        length = len(preview)
        if length < 30:
            return 0.1  # too short — probably garbage
        elif length < 50:
            return 0.4
        elif length <= 500:
            return 1.0  # sweet spot
        elif length <= 1000:
            return 0.8  # verbose but acceptable
        elif length <= 2000:
            return 0.6  # too verbose
        else:
            return 0.4  # excessively verbose

    scores = {}
    for r in results:
        if r["success"]:
            speed_norm = 1.0 - (r["duration_ms"] / max_duration)
            quality_norm = _response_quality(r)
            score = 50.0 + (speed_norm * 10.0) + (quality_norm * 40.0)
        else:
            score = 0.0
        scores[r["agent_name"]] = round(score, 1)

    # Rank by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _write(c):
        cur = c.cursor()
        for rank, (agent_name, score) in enumerate(ranked, 1):
            cur.execute(
                """
                UPDATE action_benchmark_results
                SET score = %s, rank = %s
                WHERE run_id = %s AND agent_name = %s
                """,
                (score, rank, run_id, agent_name),
            )
        cur.close()

    try:
        if conn:
            _write(conn)
        else:
            with get_db_connection() as pool_conn:
                _write(pool_conn)
                pool_conn.commit()
    except Exception as e:
        logger.error("Failed to update scores for run %d: %s", run_id, e)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def get_benchmark_results(run_id: int) -> Optional[Dict]:
    """Return full run info + ranked leaderboard for *run_id*."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Run info
            cur.execute(
                """
                SELECT id, action_key, station_code, test_config,
                       total_agents, completed_agents, failed_agents,
                       status, started_at, completed_at
                FROM action_benchmark_runs
                WHERE id = %s
                """,
                (run_id,),
            )
            run = cur.fetchone()
            if not run:
                return None

            # Results
            cur.execute(
                """
                SELECT agent_id, agent_name, display_name, model_used,
                       provider, duration_ms, prompt_tokens,
                       completion_tokens, total_tokens, success,
                       error_message, response_preview, score, rank,
                       tested_at, is_human_pick
                FROM action_benchmark_results
                WHERE run_id = %s
                ORDER BY rank ASC NULLS LAST, score DESC
                """,
                (run_id,),
            )
            results = cur.fetchall()

            return {
                "run": _row_to_dict(
                    run,
                    [
                        "id",
                        "action_key",
                        "station_code",
                        "test_config",
                        "total_agents",
                        "completed_agents",
                        "failed_agents",
                        "status",
                        "started_at",
                        "completed_at",
                    ],
                ),
                "results": [
                    _row_to_dict(
                        r,
                        [
                            "agent_id",
                            "agent_name",
                            "display_name",
                            "model_used",
                            "provider",
                            "duration_ms",
                            "prompt_tokens",
                            "completion_tokens",
                            "total_tokens",
                            "success",
                            "error_message",
                            "response_preview",
                            "score",
                            "rank",
                            "tested_at",
                            "is_human_pick",
                        ],
                    )
                    for r in results
                ],
            }
    except Exception as e:
        logger.error("Failed to get benchmark results: %s", e)
        return None


def get_latest_benchmark(action_key: str) -> Optional[Dict]:
    """Return the most recent completed benchmark for *action_key*."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id FROM action_benchmark_runs
                WHERE action_key = %s AND status = 'completed'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (action_key,),
            )
            row = cur.fetchone()
            if not row:
                return None

            run_id = row[0] if isinstance(row, tuple) else row["id"]
            return get_benchmark_results(run_id)
    except Exception as e:
        logger.error("Failed to get latest benchmark: %s", e)
        return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _row_to_dict(row, columns: List[str]) -> Dict:
    """Convert a DB row (tuple or dict) to a dict with *columns* keys."""
    if isinstance(row, dict):
        return {c: row.get(c) for c in columns}
    return {c: row[i] for i, c in enumerate(columns)}


# ---------------------------------------------------------------------------
# Benchmark → Skills feedback loop (Phase 5)
# ---------------------------------------------------------------------------
def _score_to_proficiency(score: float) -> int:
    """Convert benchmark score (0-100) to proficiency level (1-5).

    Thresholds are calibrated against the scoring formula where:
    - 50 = succeeded but poor quality/very slow
    - 60 = succeeded with mediocre quality
    - 70 = succeeded with decent quality, average speed
    - 80 = succeeded with good quality, good speed
    - 90 = succeeded with excellent quality, fast

    Levels:
    - 5 (Expert):      >= 90  — top performers, excellent quality + speed
    - 4 (Proficient):  >= 80  — strong results, good quality
    - 3 (Competent):   >= 70  — solid, gets the job done well
    - 2 (Developing):  >= 55  — completed but below average quality
    - 1 (Novice):       < 55  — poor results or failed
    """
    if score is None:
        return 1
    if score >= 90:
        return 5
    elif score >= 80:
        return 4
    elif score >= 70:
        return 3
    elif score >= 55:
        return 2
    return 1


def sync_skills_from_benchmark(run_id: int, conn=None) -> Dict:
    """Auto-adjust agent_skills from benchmark results.

    Called after ``_compute_scores()`` in the benchmark thread.

    1. Look up the benchmark run's capability → skill_name via capability_skill_map.
    2. For each successful result, convert score → proficiency (1-5) and UPSERT.
    3. For failed results, set proficiency to 1 (minimum).
    4. Record every change in benchmark_skill_updates.
    5. Invalidate the dispatcher's agent cache so new scores take effect.

    If *conn* is provided, uses it directly (no pool checkout).

    Returns ``{skill_name, updates: [{agent_name, old_level, new_level, score}]}``.
    """
    updates = []
    _own_conn = False

    try:
        if conn is None:
            from database import get_db_connection as _gdc

            _cm = _gdc()
            conn = _cm.__enter__()
            _own_conn = True

        cur = conn.cursor()

        # Load run info + capability
        cur.execute(
            """
            SELECT test_config FROM action_benchmark_runs WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return {"skill_name": None, "updates": []}

        test_config = row[0] if isinstance(row, tuple) else row["test_config"]
        if isinstance(test_config, str):
            test_config = __import__("json").loads(test_config)
        capability = (test_config or {}).get("capability", "general")

        # Map capability → skill_name
        cur.execute(
            "SELECT skill_name FROM capability_skill_map WHERE capability = %s",
            (capability,),
        )
        mapping = cur.fetchone()
        skill_name = (mapping[0] if isinstance(mapping, tuple) else mapping["skill_name"]) if mapping else capability

        # Load benchmark results for this run
        cur.execute(
            """
            SELECT agent_id, agent_name, success, score
            FROM action_benchmark_results
            WHERE run_id = %s
            """,
            (run_id,),
        )
        results = cur.fetchall()

        for r in results:
            if isinstance(r, tuple):
                agent_id, agent_name, success, score = r
            else:
                agent_id = r["agent_id"]
                agent_name = r["agent_name"]
                success = r["success"]
                score = r["score"]

            new_level = _score_to_proficiency(score) if success else 1

            # Get current proficiency
            cur.execute(
                """
                SELECT proficiency_level FROM agent_skills
                WHERE agent_id = %s AND skill_name = %s
                """,
                (agent_id, skill_name),
            )
            existing = cur.fetchone()
            old_level = (
                (existing[0] if isinstance(existing, tuple) else existing["proficiency_level"]) if existing else None
            )

            # UPSERT agent_skills
            cur.execute(
                """
                INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, updated_at)
                VALUES (%s, %s, 'benchmark', %s, NOW())
                ON CONFLICT (agent_id, skill_name) DO UPDATE
                    SET proficiency_level = EXCLUDED.proficiency_level,
                        updated_at = NOW()
                """,
                (agent_id, skill_name, new_level),
            )

            # Audit row
            cur.execute(
                """
                INSERT INTO benchmark_skill_updates
                    (run_id, agent_id, agent_name, skill_name,
                     old_level, new_level, benchmark_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, agent_id, agent_name, skill_name, old_level, new_level, score or 0.0),
            )

            updates.append(
                {
                    "agent_name": agent_name,
                    "skill": skill_name,
                    "old_level": old_level,
                    "new_level": new_level,
                    "score": score or 0.0,
                }
            )

        cur.close()
        if _own_conn:
            conn.commit()

    except Exception as e:
        logger.error("sync_skills_from_benchmark failed for run %d: %s", run_id, e)
        return {"skill_name": None, "updates": [], "error": str(e)}
    finally:
        if _own_conn and conn:
            try:
                conn.close()
            except Exception:
                pass

    # Invalidate dispatcher cache so new skill levels take effect
    if BRIDGE_AVAILABLE and _dispatcher:
        try:
            _dispatcher._cache_time = 0  # force refresh on next request
        except Exception:
            pass

    logger.info(
        "Benchmark run %d → synced %d agent skill levels for '%s'",
        run_id,
        len(updates),
        updates[0]["skill"] if updates else "none",
    )

    return {
        "skill_name": updates[0]["skill"] if updates else None,
        "updates": updates,
    }


def get_skill_updates(run_id: int) -> Optional[Dict]:
    """Return skill adjustments made by a specific benchmark run."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT agent_name, skill_name, old_level, new_level,
                       benchmark_score, updated_at
                FROM benchmark_skill_updates
                WHERE run_id = %s
                ORDER BY new_level DESC, benchmark_score DESC
                """,
                (run_id,),
            )
            rows = cur.fetchall()
            cols = [
                "agent_name",
                "skill_name",
                "old_level",
                "new_level",
                "benchmark_score",
                "updated_at",
            ]
            updates = [_row_to_dict(r, cols) for r in rows]

            # Serialize datetimes
            for u in updates:
                if u.get("updated_at") and hasattr(u["updated_at"], "isoformat"):
                    u["updated_at"] = u["updated_at"].isoformat()

            return {
                "updates": updates,
                "total_updated": len(updates),
            }
    except Exception as e:
        logger.error("get_skill_updates failed for run %d: %s", run_id, e)
        return {"updates": [], "total_updated": 0}


# ---------------------------------------------------------------------------
# Recommendation Engine (Phase 6)
# ---------------------------------------------------------------------------
def generate_station_recommendations(station_code: str = None) -> List[Dict]:
    """Generate assignment recommendations from benchmark data.

    For each station (or a specific one):
    1. Get all actions + their latest completed benchmark runs.
    2. Aggregate avg scores per agent across actions.
    3. Rank top 3, note human picks, compare vs currently assigned.
    4. Expire old pending recommendations, insert new ones if the
       algorithm's top pick differs from the current assignee.

    Returns list of new recommendation dicts.
    """
    import json as _json

    new_recs = []

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Get stations to process
            if station_code:
                stations = [station_code]
            else:
                cur.execute("SELECT DISTINCT station_code FROM station_actions " "WHERE is_active = TRUE")
                stations = [r[0] for r in cur.fetchall()]

            for stn in stations:
                # Get all actions for this station
                cur.execute(
                    "SELECT action_key FROM station_actions "
                    "WHERE station_code = %s AND is_active = TRUE "
                    "AND test_config IS NOT NULL",
                    (stn,),
                )
                action_keys = [r[0] for r in cur.fetchall()]
                if not action_keys:
                    continue

                # Collect latest benchmark results per action
                agent_scores = {}  # agent_name -> {scores:[], id, display_name, human_pick}
                tested_keys = []

                for ak in action_keys:
                    cur.execute(
                        "SELECT id FROM action_benchmark_runs "
                        "WHERE action_key = %s AND status = 'completed' "
                        "ORDER BY started_at DESC LIMIT 1",
                        (ak,),
                    )
                    run_row = cur.fetchone()
                    if not run_row:
                        continue

                    run_id = run_row[0]
                    tested_keys.append(ak)

                    cur.execute(
                        "SELECT agent_id, agent_name, display_name, score, "
                        "       success, is_human_pick "
                        "FROM action_benchmark_results "
                        "WHERE run_id = %s",
                        (run_id,),
                    )
                    for row in cur.fetchall():
                        aid, aname, dname, score, success, is_hp = row
                        if aname not in agent_scores:
                            agent_scores[aname] = {
                                "id": aid,
                                "display_name": dname or aname,
                                "scores": [],
                                "human_pick": False,
                            }
                        if success and score is not None:
                            agent_scores[aname]["scores"].append(score)
                        if is_hp:
                            agent_scores[aname]["human_pick"] = True

                if not agent_scores or not tested_keys:
                    continue

                # Compute avg score per agent (only those with results)
                ranked = []
                for aname, info in agent_scores.items():
                    scores = info["scores"]
                    avg = sum(scores) / len(scores) if scores else 0.0
                    ranked.append(
                        {
                            "agent_name": aname,
                            "agent_id": info["id"],
                            "display_name": info["display_name"],
                            "avg_score": round(avg, 1),
                            "human_pick": info["human_pick"],
                        }
                    )

                # Human picks get a tie-breaker boost (sort first by human_pick desc, then score)
                ranked.sort(
                    key=lambda x: (x["human_pick"], x["avg_score"]),
                    reverse=True,
                )
                top_3 = ranked[:3]

                if not top_3:
                    continue

                recommended = top_3[0]

                # Get currently assigned agent for this station
                cur.execute(
                    "SELECT a.id, a.name, a.display_name "
                    "FROM station_assignments sa "
                    "JOIN bridge_stations bs ON bs.id = sa.station_id "
                    "JOIN agents a ON a.id = sa.agent_id "
                    "WHERE bs.station_code = %s AND sa.is_active = TRUE "
                    "ORDER BY sa.assigned_at DESC LIMIT 1",
                    (stn,),
                )
                current_row = cur.fetchone()
                current_id = current_row[0] if current_row else None
                current_name = current_row[1] if current_row else None

                # Calculate score delta
                current_score = 0.0
                if current_name:
                    for r in ranked:
                        if r["agent_name"] == current_name:
                            current_score = r["avg_score"]
                            break
                score_delta = round(recommended["avg_score"] - current_score, 1)

                # Only create recommendation if top pick differs from current
                if recommended["agent_name"] == current_name:
                    continue

                # Expire old pending recs for this station
                cur.execute(
                    "UPDATE benchmark_recommendations "
                    "SET status = 'expired' "
                    "WHERE station_code = %s AND status = 'pending'",
                    (stn,),
                )

                # Find human pick agent name (if any)
                hp_agent = None
                for r in ranked:
                    if r["human_pick"]:
                        hp_agent = r["agent_name"]
                        break

                # Insert new recommendation
                top_3_json = _json.dumps(
                    [
                        {
                            "agent_name": t["agent_name"],
                            "display_name": t["display_name"],
                            "avg_score": t["avg_score"],
                            "human_pick": t["human_pick"],
                        }
                        for t in top_3
                    ]
                )

                cur.execute(
                    """
                    INSERT INTO benchmark_recommendations
                        (station_code, recommended_agent_id, recommended_agent_name,
                         current_agent_id, current_agent_name,
                         avg_score, score_delta, top_3,
                         human_pick_agent, action_keys_tested)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        stn,
                        recommended["agent_id"],
                        recommended["agent_name"],
                        current_id,
                        current_name,
                        recommended["avg_score"],
                        score_delta,
                        top_3_json,
                        hp_agent,
                        _json.dumps(tested_keys),
                    ),
                )
                rec_id = cur.fetchone()[0]
                conn.commit()

                new_recs.append(
                    {
                        "id": rec_id,
                        "station_code": stn,
                        "recommended_agent_name": recommended["agent_name"],
                        "recommended_display_name": recommended["display_name"],
                        "current_agent_name": current_name,
                        "avg_score": recommended["avg_score"],
                        "score_delta": score_delta,
                        "top_3": top_3,
                    }
                )

            cur.close()

    except Exception as e:
        logger.error("generate_station_recommendations failed: %s", e)

    logger.info(
        "Generated %d station recommendations%s",
        len(new_recs),
        f" for {station_code}" if station_code else "",
    )
    return new_recs


def get_station_recommendations(station_code: str = None, status: str = "pending") -> List[Dict]:
    """Query benchmark_recommendations with optional filters."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            sql = (
                "SELECT id, station_code, recommended_agent_id, "
                "  recommended_agent_name, current_agent_id, current_agent_name, "
                "  avg_score, score_delta, top_3, human_pick_agent, "
                "  action_keys_tested, status, generated_at, resolved_at, resolved_by "
                "FROM benchmark_recommendations WHERE 1=1"
            )
            params = []

            if station_code:
                sql += " AND station_code = %s"
                params.append(station_code)
            if status:
                sql += " AND status = %s"
                params.append(status)

            sql += " ORDER BY generated_at DESC"
            cur.execute(sql, params)
            rows = cur.fetchall()

            cols = [
                "id",
                "station_code",
                "recommended_agent_id",
                "recommended_agent_name",
                "current_agent_id",
                "current_agent_name",
                "avg_score",
                "score_delta",
                "top_3",
                "human_pick_agent",
                "action_keys_tested",
                "status",
                "generated_at",
                "resolved_at",
                "resolved_by",
            ]
            recs = [_row_to_dict(r, cols) for r in rows]

            # Serialize datetimes
            for rec in recs:
                for key in ("generated_at", "resolved_at"):
                    if rec.get(key) and hasattr(rec[key], "isoformat"):
                        rec[key] = rec[key].isoformat()

            # Add display names from agents table
            agent_ids = set()
            for rec in recs:
                if rec.get("recommended_agent_id"):
                    agent_ids.add(rec["recommended_agent_id"])
                if rec.get("current_agent_id"):
                    agent_ids.add(rec["current_agent_id"])

            display_names = {}
            if agent_ids:
                cur.execute(
                    "SELECT id, display_name FROM agents WHERE id = ANY(%s)",
                    (list(agent_ids),),
                )
                for row in cur.fetchall():
                    aid = row[0] if isinstance(row, tuple) else row["id"]
                    dn = row[1] if isinstance(row, tuple) else row["display_name"]
                    display_names[aid] = dn

            for rec in recs:
                rec["recommended_display_name"] = display_names.get(
                    rec.get("recommended_agent_id"), rec.get("recommended_agent_name")
                )
                rec["current_display_name"] = display_names.get(
                    rec.get("current_agent_id"), rec.get("current_agent_name")
                )

            cur.close()
            return recs

    except Exception as e:
        logger.error("get_station_recommendations failed: %s", e)
        return []


def resolve_recommendation(rec_id: int, approved: bool, user_id: int = None) -> Dict:
    """Approve or reject a recommendation.

    If approved, reassigns the station: unassigns old agent, assigns new one.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Load the recommendation
            cur.execute(
                "SELECT station_code, recommended_agent_id, "
                "  recommended_agent_name, current_agent_id, status "
                "FROM benchmark_recommendations WHERE id = %s",
                (rec_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"success": False, "error": "Recommendation not found"}

            stn, rec_agent_id, rec_agent_name, cur_agent_id, cur_status = row

            if cur_status != "pending":
                return {
                    "success": False,
                    "error": f"Recommendation already {cur_status}",
                }

            new_status = "approved" if approved else "rejected"

            cur.execute(
                """
                UPDATE benchmark_recommendations
                SET status = %s, resolved_at = NOW(), resolved_by = %s
                WHERE id = %s
                """,
                (new_status, user_id, rec_id),
            )

            if approved and rec_agent_id:
                # Look up station_id from bridge_stations
                cur.execute(
                    "SELECT id FROM bridge_stations WHERE station_code = %s",
                    (stn,),
                )
                stn_row = cur.fetchone()
                stn_id = stn_row[0] if stn_row else None

                if stn_id:
                    # Deactivate current assignment for this station
                    if cur_agent_id:
                        cur.execute(
                            "UPDATE station_assignments "
                            "SET is_active = FALSE "
                            "WHERE station_id = %s AND agent_id = %s "
                            "AND is_active = TRUE",
                            (stn_id, cur_agent_id),
                        )

                    # Create new assignment
                    cur.execute(
                        """
                        INSERT INTO station_assignments
                            (station_id, agent_id, assigned_by, is_active)
                        VALUES (%s, %s, %s, TRUE)
                        ON CONFLICT DO NOTHING
                        """,
                        (stn_id, rec_agent_id, user_id),
                    )

            conn.commit()
            cur.close()

            # Invalidate dispatcher cache
            if BRIDGE_AVAILABLE and _dispatcher:
                try:
                    _dispatcher._cache_time = 0
                except Exception:
                    pass

            return {
                "success": True,
                "status": new_status,
                "station_code": stn,
                "agent_name": rec_agent_name,
            }

    except Exception as e:
        logger.error("resolve_recommendation failed for %d: %s", rec_id, e)
        return {"success": False, "error": str(e)}


def get_station_summary() -> List[Dict]:
    """Per-station summary: current agent, top 3 from benchmarks, human pick.

    Used by the COMMAND overview panel.
    """
    import json as _json

    summaries = []
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Get all stations that have actions
            cur.execute(
                "SELECT DISTINCT station_code FROM station_actions "
                "WHERE is_active = TRUE AND test_config IS NOT NULL "
                "ORDER BY station_code"
            )
            stations = [r[0] for r in cur.fetchall()]

            for stn in stations:
                # Current assigned agents
                cur.execute(
                    "SELECT a.id, a.name, a.display_name "
                    "FROM station_assignments sa "
                    "JOIN bridge_stations bs ON bs.id = sa.station_id "
                    "JOIN agents a ON a.id = sa.agent_id "
                    "WHERE bs.station_code = %s AND sa.is_active = TRUE",
                    (stn,),
                )
                assigned = []
                for row in cur.fetchall():
                    assigned.append(
                        {
                            "id": row[0],
                            "name": row[1],
                            "display_name": row[2] or row[1],
                        }
                    )

                # Latest pending recommendation
                cur.execute(
                    "SELECT id, recommended_agent_name, avg_score, "
                    "  score_delta, top_3, human_pick_agent, generated_at "
                    "FROM benchmark_recommendations "
                    "WHERE station_code = %s AND status = 'pending' "
                    "ORDER BY generated_at DESC LIMIT 1",
                    (stn,),
                )
                rec_row = cur.fetchone()
                pending_rec = None
                if rec_row:
                    gen_at = rec_row[6]
                    if hasattr(gen_at, "isoformat"):
                        gen_at = gen_at.isoformat()
                    pending_rec = {
                        "id": rec_row[0],
                        "recommended_agent_name": rec_row[1],
                        "avg_score": rec_row[2],
                        "score_delta": rec_row[3],
                        "top_3": rec_row[4] if isinstance(rec_row[4], list) else _json.loads(rec_row[4] or "[]"),
                        "human_pick_agent": rec_row[5],
                        "generated_at": gen_at,
                    }

                # Latest benchmark date for any action in this station
                cur.execute(
                    "SELECT MAX(abr.completed_at) "
                    "FROM action_benchmark_runs abr "
                    "JOIN station_actions sa ON sa.action_key = abr.action_key "
                    "WHERE sa.station_code = %s AND abr.status = 'completed'",
                    (stn,),
                )
                latest_row = cur.fetchone()
                latest_benchmark = None
                if latest_row and latest_row[0]:
                    latest_benchmark = (
                        latest_row[0].isoformat() if hasattr(latest_row[0], "isoformat") else str(latest_row[0])
                    )

                # Action count
                cur.execute(
                    "SELECT COUNT(*) FROM station_actions "
                    "WHERE station_code = %s AND is_active = TRUE "
                    "AND test_config IS NOT NULL",
                    (stn,),
                )
                action_count = cur.fetchone()[0]

                summaries.append(
                    {
                        "station_code": stn,
                        "assigned_agents": assigned,
                        "pending_recommendation": pending_rec,
                        "latest_benchmark": latest_benchmark,
                        "action_count": action_count,
                    }
                )

            cur.close()

    except Exception as e:
        logger.error("get_station_summary failed: %s", e)

    return summaries


# ---------------------------------------------------------------------------
# Score Matrix & Optimal Placement (Bridge as Single Source of Truth)
# ---------------------------------------------------------------------------


def get_score_matrix() -> Dict:
    """Return agent×station score grid for heatmap display.

    Returns:
        {
            "agents": [{"id": 1, "name": "Nexus", "display_name": "Jin Park"}, ...],
            "stations": ["ANALYTICS", "COMMAND", ...],
            "scores": {
                "Nexus": {"ANALYTICS": 87.2, "COMMAND": 65.1, ...},
                ...
            },
            "current_assignments": {
                "ANALYTICS": [{"agent_id": 8, "agent_name": "DataMind", "type": "primary"}, ...],
                ...
            },
            "human_picks": {
                "Nexus": {"ANALYTICS": True},  # agent has human_pick at this station
                ...
            }
        }
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Get all stations with actions
            cur.execute(
                "SELECT DISTINCT station_code FROM station_actions "
                "WHERE is_active = TRUE AND test_config IS NOT NULL "
                "ORDER BY station_code"
            )
            stations = [r[0] for r in cur.fetchall()]

            # Get all agents
            cur.execute("SELECT id, name, display_name FROM agents " "ORDER BY name")
            agents = []
            for r in cur.fetchall():
                agents.append(
                    {
                        "id": r[0],
                        "name": r[1],
                        "display_name": r[2] or r[1],
                    }
                )

            # Build score matrix: for each station, get avg score per agent
            # across all actions' latest completed benchmarks
            scores = {}  # agent_name -> {station_code -> avg_score}
            human_picks = {}  # agent_name -> {station_code -> True}

            for stn in stations:
                # Get action keys for this station
                cur.execute(
                    "SELECT action_key FROM station_actions "
                    "WHERE station_code = %s AND is_active = TRUE "
                    "AND test_config IS NOT NULL",
                    (stn,),
                )
                action_keys = [r[0] for r in cur.fetchall()]

                # Collect scores across all actions for this station
                agent_stn_scores = {}  # agent_name -> [scores]
                agent_stn_picks = {}  # agent_name -> bool

                for ak in action_keys:
                    cur.execute(
                        "SELECT id FROM action_benchmark_runs "
                        "WHERE action_key = %s AND status = 'completed' "
                        "ORDER BY started_at DESC LIMIT 1",
                        (ak,),
                    )
                    run_row = cur.fetchone()
                    if not run_row:
                        continue

                    cur.execute(
                        "SELECT agent_name, score, success, is_human_pick "
                        "FROM action_benchmark_results WHERE run_id = %s",
                        (run_row[0],),
                    )
                    for row in cur.fetchall():
                        aname, score, success, is_hp = row
                        if success and score is not None:
                            if aname not in agent_stn_scores:
                                agent_stn_scores[aname] = []
                            agent_stn_scores[aname].append(score)
                        if is_hp:
                            agent_stn_picks[aname] = True

                for aname, stn_scores in agent_stn_scores.items():
                    if aname not in scores:
                        scores[aname] = {}
                    scores[aname][stn] = round(sum(stn_scores) / len(stn_scores), 1)

                for aname in agent_stn_picks:
                    if aname not in human_picks:
                        human_picks[aname] = {}
                    human_picks[aname][stn] = True

            # Current assignments
            current_assignments = {}
            for stn in stations:
                cur.execute(
                    "SELECT a.id, a.name, a.display_name, sa.assignment_type "
                    "FROM station_assignments sa "
                    "JOIN bridge_stations bs ON bs.id = sa.station_id "
                    "JOIN agents a ON a.id = sa.agent_id "
                    "WHERE bs.station_code = %s AND sa.is_active = TRUE",
                    (stn,),
                )
                current_assignments[stn] = []
                for row in cur.fetchall():
                    current_assignments[stn].append(
                        {
                            "agent_id": row[0],
                            "agent_name": row[1],
                            "display_name": row[2] or row[1],
                            "type": row[3],
                        }
                    )

            cur.close()

            return {
                "agents": agents,
                "stations": stations,
                "scores": scores,
                "current_assignments": current_assignments,
                "human_picks": human_picks,
            }

    except Exception as e:
        logger.error("get_score_matrix failed: %s", e)
        return {
            "agents": [],
            "stations": [],
            "scores": {},
            "current_assignments": {},
            "human_picks": {},
        }


def generate_optimal_placement() -> Dict:
    """Build optimal agent placement plan using greedy algorithm.

    Algorithm:
    1. Build score matrix: agents × stations (from benchmark results).
    2. Skip COMMAND station (ARCHIE + Vigil are fixed there).
    3. Exclude fixed agents (is_fixed=TRUE) from the assignment pool.
    4. Lock human-picked assignments (is_human_pick=TRUE).
    5. Sort stations by "score gap" (diff between #1 and #2 candidate) — largest gap first.
    6. Greedy: assign best available agent as primary to each station.
    7. Assign second-best available as secondary.
    8. Remaining agents go to auxiliary pool.

    Returns placement plan (not applied — needs human approval).
    """
    import json as _json

    matrix = get_score_matrix()
    stations = matrix["stations"]
    scores = matrix["scores"]
    current = matrix["current_assignments"]
    human_picks = matrix["human_picks"]

    # Skip COMMAND — fixed seats (ARCHIE + Vigil), not reassignable
    stations = [s for s in stations if s != "COMMAND"]

    # Build agent lookup — only active agents
    agent_lookup = {a["name"]: a for a in matrix["agents"] if a.get("status", "active") == "active"}

    # Find fixed agents (is_fixed=TRUE in station_assignments) — exclude from pool
    fixed_agents = set()
    try:
        with get_db_connection() as conn:
            _cur = conn.cursor()
            _cur.execute(
                "SELECT a.name FROM station_assignments sa "
                "JOIN agents a ON a.id = sa.agent_id "
                "WHERE sa.is_fixed = TRUE AND sa.is_active = TRUE"
            )
            fixed_agents = {r[0] for r in _cur.fetchall()}
            _cur.close()
    except Exception:
        pass

    # Remove fixed agents from scores (they can't be reassigned)
    for fa in fixed_agents:
        scores.pop(fa, None)

    # Identify human-locked assignments (agents marked as human_pick at a station)
    locked = {}  # station_code -> agent_name
    for aname, stn_picks in human_picks.items():
        if aname in fixed_agents:
            continue
        for stn_code in stn_picks:
            # Only lock if this agent actually has the best human_pick for this station
            if stn_code not in locked:
                locked[stn_code] = aname

    # For each station, rank agents by avg score
    station_rankings = {}
    for stn in stations:
        ranking = []
        for aname, stn_scores in scores.items():
            if stn in stn_scores:
                ranking.append(
                    {
                        "agent_name": aname,
                        "avg_score": stn_scores[stn],
                        "agent_id": agent_lookup[aname]["id"] if aname in agent_lookup else None,
                        "display_name": agent_lookup[aname]["display_name"] if aname in agent_lookup else aname,
                    }
                )
        ranking.sort(key=lambda x: x["avg_score"], reverse=True)
        station_rankings[stn] = ranking

    # Calculate score gaps for sorting priority
    station_gaps = []
    for stn in stations:
        ranking = station_rankings.get(stn, [])
        if len(ranking) >= 2:
            gap = ranking[0]["avg_score"] - ranking[1]["avg_score"]
        elif len(ranking) == 1:
            gap = ranking[0]["avg_score"]  # huge gap — only one candidate
        else:
            gap = 0
        station_gaps.append({"station_code": stn, "gap": gap})

    # Sort by gap descending — assign stations with largest gap first
    station_gaps.sort(key=lambda x: x["gap"], reverse=True)

    # Greedy assignment — each agent assigned to exactly 1 station
    taken = set()  # agent names already assigned (primary OR secondary)
    placements = []

    # First pass: honor locked (human-picked) assignments
    for stn_code, aname in locked.items():
        taken.add(aname)

    for sg in station_gaps:
        stn = sg["station_code"]
        ranking = station_rankings.get(stn, [])
        human_locked = stn in locked

        # Primary assignment
        primary = None
        if human_locked:
            # Use the locked agent
            aname = locked[stn]
            for r in ranking:
                if r["agent_name"] == aname:
                    primary = r
                    break
            if not primary and aname in agent_lookup:
                primary = {
                    "agent_name": aname,
                    "agent_id": agent_lookup[aname]["id"],
                    "display_name": agent_lookup[aname]["display_name"],
                    "avg_score": scores.get(aname, {}).get(stn, 0),
                }
        else:
            # Best available agent
            for r in ranking:
                if r["agent_name"] not in taken:
                    primary = r
                    taken.add(r["agent_name"])
                    break

        # Secondary assignment (best available not already taken anywhere)
        secondary = None
        for r in ranking:
            if primary and r["agent_name"] == primary["agent_name"]:
                continue
            if r["agent_name"] not in taken:
                secondary = r
                taken.add(r["agent_name"])  # Mark taken — 1 station per agent
                break

        # Current assignment for comparison
        current_agents = current.get(stn, [])
        current_primary = None
        for ca in current_agents:
            if ca["type"] == "primary":
                current_primary = ca
                break

        placements.append(
            {
                "station_code": stn,
                "primary": primary,
                "secondary": secondary,
                "human_locked": human_locked,
                "score_gap": round(sg["gap"], 1),
                "current_primary": current_primary,
                "changed": (
                    primary is not None
                    and (current_primary is None or current_primary["agent_name"] != primary["agent_name"])
                ),
            }
        )

    # Sort placements back to alphabetical for display
    placements.sort(key=lambda x: x["station_code"])

    # Unassigned agents (not placed at any station in the plan)
    all_agents_with_scores = set(scores.keys())
    unassigned = []
    for aname in all_agents_with_scores:
        if aname not in taken and aname in agent_lookup:
            unassigned.append(
                {
                    "agent_id": agent_lookup[aname]["id"],
                    "name": aname,
                    "display_name": agent_lookup[aname]["display_name"],
                }
            )

    return {
        "placements": placements,
        "unassigned": unassigned,
        "total_stations": len(stations),
        "total_agents": len(all_agents_with_scores),
    }


def apply_placement(placement_plan: Dict, user_id: int = None) -> Dict:
    """Execute an approved placement plan.

    For each station in the plan:
    1. Skip COMMAND (fixed seats — ARCHIE + Vigil).
    2. Skip fixed assignments (is_fixed=TRUE).
    3. Deactivate current non-fixed primary assignments at that station.
    4. Assign the new primary agent.
    5. Optionally assign secondary as backup.

    All within a single transaction — rolls back on error.
    """
    applied = []
    errors = []

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            for p in placement_plan.get("placements", []):
                stn_code = p["station_code"]
                primary = p.get("primary")
                secondary = p.get("secondary")

                # Never touch COMMAND — fixed seats
                if stn_code == "COMMAND":
                    continue

                if not primary:
                    continue

                # Skip unchanged stations
                if not p.get("changed", True):
                    continue

                try:
                    # Look up station_id
                    cur.execute(
                        "SELECT id FROM bridge_stations WHERE station_code = %s",
                        (stn_code,),
                    )
                    stn_row = cur.fetchone()
                    if not stn_row:
                        errors.append(
                            {
                                "station_code": stn_code,
                                "error": "Station not found",
                            }
                        )
                        continue
                    stn_id = stn_row[0]

                    # Skip if primary agent has a fixed assignment elsewhere
                    cur.execute(
                        "SELECT 1 FROM station_assignments "
                        "WHERE agent_id = %s AND is_fixed = TRUE AND is_active = TRUE",
                        (primary["agent_id"],),
                    )
                    if cur.fetchone():
                        errors.append(
                            {
                                "station_code": stn_code,
                                "error": f"{primary['agent_name']} has a fixed assignment",
                            }
                        )
                        continue

                    # Deactivate ALL current non-fixed assignments at this station
                    cur.execute(
                        "UPDATE station_assignments "
                        "SET is_active = FALSE "
                        "WHERE station_id = %s "
                        "AND is_active = TRUE AND is_fixed = FALSE",
                        (stn_id,),
                    )

                    # Deactivate primary agent's existing assignment elsewhere
                    # (1 station per agent rule)
                    cur.execute(
                        "UPDATE station_assignments "
                        "SET is_active = FALSE "
                        "WHERE agent_id = %s "
                        "AND is_active = TRUE AND is_fixed = FALSE",
                        (primary["agent_id"],),
                    )

                    # Assign new primary
                    cur.execute(
                        """
                        INSERT INTO station_assignments
                            (station_id, agent_id, assignment_type,
                             assigned_by, is_active)
                        VALUES (%s, %s, 'primary', %s, TRUE)
                        ON CONFLICT (station_id, agent_id) DO UPDATE
                            SET assignment_type = 'primary',
                                is_active = TRUE,
                                assigned_by = EXCLUDED.assigned_by,
                                assigned_at = NOW()
                        """,
                        (stn_id, primary["agent_id"], user_id),
                    )

                    # Assign secondary (if provided)
                    if secondary and secondary.get("agent_id"):
                        # Deactivate secondary's existing assignment elsewhere
                        cur.execute(
                            "UPDATE station_assignments "
                            "SET is_active = FALSE "
                            "WHERE agent_id = %s "
                            "AND is_active = TRUE AND is_fixed = FALSE",
                            (secondary["agent_id"],),
                        )

                        cur.execute(
                            """
                            INSERT INTO station_assignments
                                (station_id, agent_id, assignment_type,
                                 assigned_by, is_active)
                            VALUES (%s, %s, 'primary', %s, TRUE)
                            ON CONFLICT (station_id, agent_id) DO UPDATE
                                SET assignment_type = 'primary',
                                    is_active = TRUE,
                                    assigned_by = EXCLUDED.assigned_by,
                                    assigned_at = NOW()
                            """,
                            (stn_id, secondary["agent_id"], user_id),
                        )

                    applied.append(
                        {
                            "station_code": stn_code,
                            "primary": primary["agent_name"],
                            "secondary": secondary["agent_name"] if secondary else None,
                        }
                    )

                except Exception as e:
                    errors.append(
                        {
                            "station_code": stn_code,
                            "error": str(e),
                        }
                    )

            if errors:
                conn.rollback()
                return {
                    "success": False,
                    "applied": [],
                    "errors": errors,
                    "error": "Some assignments failed — rolled back",
                }

            conn.commit()
            cur.close()

    except Exception as e:
        logger.error("apply_placement failed: %s", e)
        return {"success": False, "error": str(e), "applied": [], "errors": []}

    # Invalidate dispatcher cache
    if BRIDGE_AVAILABLE and _dispatcher:
        try:
            _dispatcher._cache_time = 0
        except Exception:
            pass

    logger.info("Applied placement plan: %d stations updated", len(applied))
    return {
        "success": True,
        "applied": applied,
        "errors": [],
    }
