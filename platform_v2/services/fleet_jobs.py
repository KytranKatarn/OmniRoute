"""services/fleet_jobs.py — Fleet/infrastructure background jobs.

Extracted from agent_loop.py (Phase 5). Each job is a standalone function.
Registration with APScheduler happens via register_fleet_jobs().

Jobs extracted:
  - agent_fleet_health (Job #45: fleet heartbeat monitor, every 30s)
  - agent_mesh_health (Job #53: mesh VPN connectivity, every 60s)
  - agent_model_state_save (Job #46: model state persistence, every 5min)
  - agent_standalone_health (Job #59: standalone product health, every 60s)
  - department_metrics_rollup (Job #60: daily at 2:00 AM)
  - fleet_ssl_renewal (Job #61: SSL cert renewal, daily at 3:00 AM)
"""

import json
import logging
import os
import time

logger = logging.getLogger("agent_loop")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FLEET_DEPARTMENT = "Operations & Infrastructure"

# Track standalone health state across calls
_standalone_last_status = {}


def _log_cycle(
    job_name: str,
    items_processed: int,
    items_failed: int,
    duration_ms: int,
    details: dict = None,
    error_message: str = None,
):
    """Log an agent loop execution cycle to autonomy_loop_log."""
    status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO autonomy_loop_log
            (job_name, status, items_processed, items_failed, duration_ms, details, error_message, department)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_name,
                status,
                items_processed,
                items_failed,
                duration_ms,
                json.dumps(details or {}),
                error_message,
                _FLEET_DEPARTMENT,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------


def check_fleet_health():
    """Job #45: Monitor fleet node heartbeats -- return agents to barracks if offline."""
    # Hub self-heartbeat — the hub doesn't run a heartbeat.sh against itself,
    # so stamp last_heartbeat directly before the fleet health check runs.
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("UPDATE remote_nodes SET last_heartbeat = NOW() WHERE deployment_mode = 'starbase'")
    except Exception as _hb_exc:
        logger.warning("Hub self-heartbeat failed: %s", _hb_exc)

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        dispatcher.check_fleet_health()
    except Exception as e:
        logger.warning(f"Fleet health check failed: {e}")


def check_mesh_health():
    """Job #53: Monitor mesh VPN connectivity for all fleet nodes.

    Pings each node's mesh_ip, updates mesh_status/mesh_latency_ms
    in remote_nodes, and logs to mesh_health_log. Triggers fleet cache
    refresh on status transitions (disconnected->connected or vice versa).
    """
    try:
        import socket
        import time as _time
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, node_name, mesh_ip, mesh_status
                   FROM remote_nodes
                   WHERE mesh_ip IS NOT NULL
                     AND is_active = true
                     AND approval_status = 'approved'"""
            )
            nodes = cur.fetchall()

        if not nodes:
            return

        changed = False
        for node in nodes:
            mesh_ip = node["mesh_ip"]
            old_status = node["mesh_status"]
            node_id = node["id"]

            # TCP connect to Ollama port on mesh IP (fast reachability check)
            latency_ms = None
            new_status = "disconnected"
            conn_type = None
            try:
                start = _time.monotonic()
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((mesh_ip, 11434))
                s.close()
                elapsed = (_time.monotonic() - start) * 1000
                latency_ms = int(elapsed)
                new_status = "connected"
                conn_type = "direct"
            except Exception:
                new_status = "disconnected"

            # Update remote_nodes
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """UPDATE remote_nodes
                       SET mesh_status = %s,
                           mesh_latency_ms = %s,
                           mesh_connection_type = %s,
                           mesh_last_seen = CASE WHEN %s = 'connected' THEN NOW() ELSE mesh_last_seen END
                       WHERE id = %s""",
                    (new_status, latency_ms, conn_type, new_status, node_id),
                )

                # Log to mesh_health_log
                cur.execute(
                    """INSERT INTO mesh_health_log
                       (node_id, mesh_ip, latency_ms, connection_type, is_reachable)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        node_id,
                        mesh_ip,
                        latency_ms,
                        conn_type,
                        new_status == "connected",
                    ),
                )
                conn.commit()

            # Detect status transitions
            if old_status != new_status:
                changed = True
                logger.info(f"[MeshHealth] Node {node['node_name']} mesh " f"{old_status}->{new_status} ({mesh_ip})")

        # Refresh fleet cache if any node changed status
        if changed:
            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                dispatcher._refresh_fleet_cache()
            except Exception:
                pass

        # Prune old health log entries (keep 7 days)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("DELETE FROM mesh_health_log WHERE checked_at < NOW() - INTERVAL '7 days'")
                conn.commit()
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Mesh health check failed: {e}")


def warmup_fleet_models():
    """Job: Keep the fleet warm-model set loaded across all nodes (every 20 min).

    Dispatches minimal "ping" requests through the DHQ dispatcher (ADR-013) so
    Ollama's KEEP_ALIVE timer resets before the 30m expiry. Dispatches fire in
    parallel (max 3 workers, 90s timeout) so the total cycle completes in ~1-2
    minutes regardless of cold-load latency.

    Entries are tagged module_id='fleet_warmup' in task_execution_log.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    warmup_capabilities = [
        ("bias_analysis", "Classify bias: 'ping'"),  # B.I.A.S. qwen2.5:1.5b — GPU fleet dispatch
        ("geo_extraction", "Location: 'Ottawa'"),  # L.O.C.A.L. llama3.2:3b — GPU fleet dispatch
        ("fact_check", "Verify: 'ping'"),  # V.E.R.I.F.Y. qwen2.5:7b — fleet dispatch
        ("documentation", "Summarize: 'ping'"),  # C.O.D.E.X. mistral:7b — fleet dispatch
        (
            "creative",
            "Synthesize: 'ping'",
        ),  # M.U.S.E. mistral:7b — portrait-refine synthesis (T3454 keep-alive: this stage cold-loaded + timed out, task 3461)
        ("workforce_planning", "Status: 'ping'"),  # K.I.N. gemma3:12b — fleet dispatch
        ("security", "Check: 'ping'"),  # S.H.I.E.L.D. qwen2.5:7b — fleet dispatch (was gemma2-cpu)
        ("conversation", "Hi"),  # D.R.A.F.T./A.C.C.O.R.D. dolphin3 — fleet dispatch
        (
            "code_review",
            "Review: 'ping'",
        ),  # F.O.R.G.E./P.R.O.B.E. coder 7B — keep warm so Repair Bay PR review never cold-loads (task 3449)
    ]

    try:
        from flask import current_app

        app = current_app._get_current_object()

        def _dispatch_one(capability, prompt):
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

                result = dispatch(
                    capability=capability,
                    prompt=prompt,
                    module_id="fleet_warmup",
                )
                return capability, result.success

        warmed = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_dispatch_one, cap, prompt): cap for cap, prompt in warmup_capabilities}
            for future in as_completed(futures, timeout=90):
                cap = futures[future]
                try:
                    _, success = future.result()
                    if success:
                        warmed += 1
                except Exception as exc:
                    logger.debug("[warmup_fleet] %s skipped: %s", cap, exc)

        logger.debug("[warmup_fleet] cycle done — %d/%d warmed", warmed, len(warmup_capabilities))
    except Exception as e:
        logger.warning("[warmup_fleet] cycle failed: %s", e)

    # Per-node pilot lights — guarantee ≥1 warm model on EVERY online node.
    _warm_node_pilot_lights()


def _warm_node_pilot_lights():
    """Keep a small 'pilot light' model warm on every online fleet node.

    The capability warmups above route via the dispatcher, which only warms the
    node it happens to pick — an idle outpost the dispatcher never selects goes
    cold and its next first dispatch eats a multi-minute cold load. This enqueues
    a low-priority warmup task pinned to EACH online node (preferred_node_id), so
    model_dispatch_worker dispatches it to that exact node, loading its smallest
    model and resetting keep_alive (30m, > the 20-min warmup interval).

    Fully ADR-013 compliant: routed through dispatch_pending_queue → the worker →
    the dispatcher (visible in task_execution_log) — never a direct Ollama call.
    priority=1 so real work always preempts; deduped + 5-min expiry so pilots
    never pile up.
    """
    from database import get_db_cursor

    # Smallest-first: cheapest useful always-ready engine per node.
    PILOT_PREFERENCE = ["qwen2.5:1.5b", "llama3.2:3b", "nomic-embed-text"]
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """
                SELECT rn.id, rn.node_name,
                       array_agg(nom.model_name) FILTER (WHERE nom.is_available) AS models
                FROM remote_nodes rn
                LEFT JOIN node_ollama_models nom ON nom.node_id = rn.node_id
                WHERE rn.is_active = TRUE
                  AND rn.status = 'online'
                  AND rn.last_heartbeat > NOW() - INTERVAL '2 minutes'
                  AND rn.deployment_mode IS DISTINCT FROM 'starbase'
                GROUP BY rn.id, rn.node_name
                """
            )
            nodes = cur.fetchall()
            queued = 0
            for n in nodes:
                models = n.get("models") or []
                if not models:
                    continue
                pilot = next((m for m in PILOT_PREFERENCE if m in models), models[0])
                # Skip if a pilot is already pending/running for this node.
                cur.execute(
                    """SELECT 1 FROM dispatch_pending_queue
                       WHERE preferred_node_id = %s AND module_id = 'fleet_pilot'
                         AND status IN ('queued', 'running') LIMIT 1""",
                    (n["id"],),
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    """
                    INSERT INTO dispatch_pending_queue
                        (capability, model_needed, prompt, preferred_node_id,
                         priority, module_id, source_product, expires_at)
                    VALUES ('warmup', %s, 'ping', %s, 1, 'fleet_pilot', 'fleet_pilot',
                            NOW() + INTERVAL '5 minutes')
                    """,
                    (pilot, n["id"]),
                )
                queued += 1
        logger.debug("[warmup_fleet] pilot lights queued for %d node(s)", queued)
    except Exception as exc:
        logger.warning("[warmup_fleet] pilot-light enqueue failed: %s", exc)


def save_model_state():
    """Job #46: Save current loaded models to DB for restart recovery."""
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        dispatcher._save_model_state()  # Hub
        # Also save state for each online node
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id FROM remote_nodes
                   WHERE is_active = true AND deployment_mode != 'starbase'
                   AND last_heartbeat > NOW() - INTERVAL '2 minutes'"""
            )
            for row in cur.fetchall():
                try:
                    dispatcher._save_model_state(node_db_id=row["id"])
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Model state save failed: {e}")


def check_standalone_health():
    """Job #59: Monitor standalone product health, alert on downtime."""
    import requests as req

    standalones = [
        {
            "name": "Kytran System Operations",
            "url": os.getenv("STANDALONE_SYSOPS_URL", "https://server.kytranempowerment.com"),
            "health_path": "/health",  # /dashboard/api/health returns 404; /health is correct
        },
    ]

    for product in standalones:
        key = product["name"]
        url = f"{product['url']}{product['health_path']}"
        was_down = _standalone_last_status.get(key) == "down"

        try:
            resp = req.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")
                # Accept both {"status": "healthy"/"operational"} and {"healthy": True} response shapes
                is_healthy = status in ("healthy", "operational") or data.get("healthy") is True
                if is_healthy:
                    if was_down:
                        # Nagios handles monitoring alerts -- log only
                        logger.info(f"[Standalone Health] {key} recovered")
                    _standalone_last_status[key] = "up"
                    continue

            # Non-200 or unhealthy status
            raise Exception(f"HTTP {resp.status_code}")

        except Exception as e:
            if not was_down:
                # Nagios handles monitoring alerts -- log only
                logger.error(f"[Standalone Health] {key} is DOWN: {e}")
            _standalone_last_status[key] = "down"


def budget_reconciliation():
    """Job: reconcile agent_budgets.current_task_count against actual in-flight
    bridge_jobs every hour. Belt-and-suspenders for the complete_job decrement
    fix (task #2100) — catches drift from crashed workers or missed code paths.

    Also emits an admin notification when any agent is budget-blocked (task #2101)
    so Department HQ / A.R.C.H.I.E. don't keep silently swallowing capability
    outages.
    """
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.agent_service import reconcile_task_counters
        from database import get_db_cursor

        corrected = reconcile_task_counters()

        # Detect any agent STILL blocked after reconciliation — genuine overcommit.
        blocked: list = []
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.name, a.display_name, a.department,
                       ab.current_task_count, ab.task_queue_limit
                FROM agents a
                JOIN agent_budgets ab ON ab.agent_id = a.id
                WHERE a.shift_state IN ('active', 'winding_down')
                  AND ab.current_task_count >= ab.task_queue_limit
                """
            )
            blocked = [dict(r) for r in cur.fetchall()]

        if blocked:
            names = ", ".join(b["name"] for b in blocked)
            logger.warning(
                "[BudgetReconcile] %d agent(s) budget-blocked after reconciliation: %s",
                len(blocked),
                names,
            )
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    msg = (
                        f"🚨 Budget exhaustion — {len(blocked)} agent(s) blocked:\n"
                        + "\n".join(
                            f"• {b['display_name']} ({b['department']}) — "
                            f"{b['current_task_count']}/{b['task_queue_limit']}"
                            for b in blocked[:10]
                        )
                        + "\n\nAgents cannot accept new dispatch until their queue clears "
                        "or task_queue_limit is raised."
                    )
                    cur.execute(
                        """INSERT INTO system_notifications
                               (type, title, message, source, priority, visibility,
                                is_read, created_at)
                           VALUES ('warning', 'Agent Budget Exhaustion',
                                   %s, 'budget_reconcile', 'high', 'admin',
                                   FALSE, NOW())""",
                        (msg,),
                    )
            except Exception as notif_err:
                logger.debug("[BudgetReconcile] notification insert failed: %s", notif_err)

        _log_cycle(
            "budget_reconciliation",
            len(corrected),
            len(blocked),
            0,
        )
    except Exception as e:
        _log_cycle("budget_reconciliation", 0, 1, 0, error_message=str(e))
        logger.warning("Budget reconciliation failed: %s", e)


def department_metrics_rollup():
    """Job #60: Department metrics rollup -- daily at 2:00 AM.
    Owned by Analytics & Intelligence (S.P.E.C.T.R.A.)."""
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.work_tracking_service import compute_department_metrics

        result = compute_department_metrics(period_hours=24)
        logger.info(
            "Department metrics rollup: %d departments computed",
            result.get("departments_computed", 0),
        )
        _log_cycle(
            "department_metrics_rollup",
            result.get("departments_computed", 0),
            0,
            0,
        )
    except Exception as e:
        _log_cycle("department_metrics_rollup", 0, 1, 0, error_message=str(e))
        logger.warning("Department metrics rollup failed: %s", e)


def renew_fleet_ssl():
    """Job #61: Renew wildcard SSL cert if expiring within 30 days.
    Owned by Security & Compliance (V.I.G.I.L.)."""
    try:
        from ai_bridge.cert_manager import check_cert_expiry, renew_wildcard_cert

        cert_dir = "/opt/archie-fleet/certs/wildcard"
        cert_path = os.path.join(cert_dir, "fullchain.pem")
        days_left = check_cert_expiry(cert_path)

        if days_left > 30:
            logger.info(f"[SSL] Wildcard cert valid for {days_left} more days, skipping renewal")
            return

        if days_left == -1:
            logger.info("[SSL] No wildcard cert found, attempting first issuance...")
        else:
            logger.info(f"[SSL] Cert expires in {days_left} days, starting renewal...")

        success, message = renew_wildcard_cert("kytranempowerment.com", cert_dir)

        if success:
            logger.info(f"[SSL] Renewal successful: {message}")
        else:
            logger.error(f"[SSL] Renewal failed: {message}")
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_notifications
                       (type, title, message, source, priority, visibility, is_read, created_at)
                       VALUES ('error', 'SSL Renewal Failed', %s, 'agent_loop', 'high', 'admin', FALSE, NOW())""",
                    (message,),
                )
    except Exception as e:
        logger.error(f"[SSL] Fleet SSL renewal error: {e}")


# ---------------------------------------------------------------------------
# VPS Health Monitor (task #1683)
# ---------------------------------------------------------------------------

_vps_last_status = {}

# Per-host probe config. Add a new host by appending a dict here.
_VPS_HOSTS = [
    {
        "name": "US Outpost (76.13.107.109)",
        "ssh_host": "76.13.107.109",
        "ssh_port": 22,
        "http_urls": [
            "https://what-the-fact.com/",
            "https://what-the-fact.tech/",
            "https://civic.kytranempowerment.com/",
            "https://legal.kytranempowerment.com/",
            "https://gov.kytranempowerment.com/",
            "https://market.kytranempowerment.com/",
        ],
    },
]


def _probe_tcp(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Return (ok, detail). No side effects."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"tcp {host}:{port} ok"
    except Exception as e:
        return False, f"tcp {host}:{port} fail: {e}"


def _probe_http(url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Return (ok, detail). 2xx/3xx counts as ok."""
    import requests as req

    try:
        r = req.get(url, timeout=timeout, allow_redirects=False, verify=True)
        if 200 <= r.status_code < 400:
            return True, f"{url} -> {r.status_code}"
        return False, f"{url} -> {r.status_code}"
    except Exception as e:
        return False, f"{url} -> {type(e).__name__}"


def check_vps_health():
    """Task #1683: probe SSH + HTTP endpoints on each VPS every 5 min.

    Writes an autonomy_loop_log row via _log_cycle and, on a transition
    from healthy -> degraded, emits a system_notifications alert
    (picked up by the existing Telegram forwarder).
    """
    start = time.time()
    total_checks = 0
    total_failures = 0
    per_host = {}

    for cfg in _VPS_HOSTS:
        host_failures = []
        # SSH probe
        ok, detail = _probe_tcp(cfg["ssh_host"], cfg["ssh_port"])
        total_checks += 1
        if not ok:
            host_failures.append(detail)
        # HTTP probes
        for url in cfg["http_urls"]:
            ok, detail = _probe_http(url)
            total_checks += 1
            if not ok:
                host_failures.append(detail)

        total_failures += len(host_failures)
        per_host[cfg["name"]] = {
            "failures": len(host_failures),
            "details": host_failures[:10],  # cap for DB/log size
        }

        # State transition detection for alerting — only fire on the edge
        prev_state = _vps_last_status.get(cfg["name"])
        new_state = "degraded" if host_failures else "healthy"
        _vps_last_status[cfg["name"]] = new_state

        if prev_state == "healthy" and new_state == "degraded":
            try:
                from database import get_db_cursor

                msg = f"{cfg['name']} — {len(host_failures)} probe(s) failing:\n" + "\n".join(
                    f"  - {d}" for d in host_failures[:5]
                )
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO system_notifications
                           (type, title, message, source, priority, visibility, is_read, created_at)
                           VALUES ('error', 'VPS Health Degraded', %s,
                                   'agent_loop', 'high', 'admin', FALSE, NOW())""",
                        (msg,),
                    )
                logger.warning(f"[VPS Health] ALERT — {cfg['name']} degraded")
            except Exception as e:
                logger.error(f"[VPS Health] failed to insert alert: {e}")
        elif prev_state == "degraded" and new_state == "healthy":
            logger.info(f"[VPS Health] {cfg['name']} recovered")

    duration_ms = int((time.time() - start) * 1000)
    _log_cycle(
        "vps_health",
        items_processed=total_checks - total_failures,
        items_failed=total_failures,
        duration_ms=duration_ms,
        details={
            "total_checks": total_checks,
            "failures": total_failures,
            "hosts": per_host,
        },
    )


# ---------------------------------------------------------------------------
# Hub Container Observer (task #2144)
# ---------------------------------------------------------------------------
# Caught 2026-04-18: archie_headscale + archie_tailscale had been missing
# from the hub for ~20h with zero alerts. check_vps_health() covers remote
# VPS but has no hub-side peer. This observer runs `docker ps` every 5min
# and fires an edge-triggered alert (exactly once per transition) when a
# CRITICAL container goes from running -> missing. Conservative list: add
# entries here as platform surfaces stabilize, don't try to cover every
# container from day 1.

_HUB_CRITICAL_CONTAINERS = [
    "archie_platform",
    "archie_database",
    "archie_comms",
    "archie_headscale",
    "archie_tailscale",
    "nginx_proxy_manager",
]

_hub_containers_last_status = {}


def _running_hub_containers() -> set[str]:
    """Return set of running container names on the hub.

    Uses docker CLI via subprocess — matches the style of other fleet_jobs
    probes and avoids adding a docker-py dependency.
    """
    import subprocess

    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return set(line.strip() for line in r.stdout.splitlines() if line.strip())
    except Exception as e:
        logger.error(f"[Hub Observer] docker ps failed: {e}")
        return set()


def check_hub_containers():
    """Task #2144: verify critical hub containers every 5 min.

    Edge-triggered: fires one alert per running -> missing transition.
    Logs recovery at INFO when a missing container comes back.
    """
    start = time.time()
    running = _running_hub_containers()
    missing = [name for name in _HUB_CRITICAL_CONTAINERS if name not in running]

    for name in _HUB_CRITICAL_CONTAINERS:
        prev = _hub_containers_last_status.get(name)
        curr = "missing" if name in missing else "running"
        _hub_containers_last_status[name] = curr

        if prev == "running" and curr == "missing":
            try:
                from database import get_db_cursor

                msg = (
                    f"Critical hub container '{name}' is not running. "
                    f"Check `docker ps` + `docker compose up -d --no-deps {name}`."
                )
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO system_notifications
                           (type, title, message, source, priority, visibility, is_read, created_at)
                           VALUES ('error', 'Hub Container Missing', %s,
                                   'agent_loop', 'high', 'admin', FALSE, NOW())""",
                        (msg,),
                    )
                logger.warning(f"[Hub Observer] ALERT — {name} missing")
            except Exception as e:
                logger.error(f"[Hub Observer] failed to insert alert: {e}")
        elif prev == "missing" and curr == "running":
            logger.info(f"[Hub Observer] {name} recovered")

    duration_ms = int((time.time() - start) * 1000)
    _log_cycle(
        "hub_containers_health",
        items_processed=len(_HUB_CRITICAL_CONTAINERS) - len(missing),
        items_failed=len(missing),
        duration_ms=duration_ms,
        details={
            "total_critical": len(_HUB_CRITICAL_CONTAINERS),
            "missing": missing,
            "running_count": len(running),
        },
    )


# ---------------------------------------------------------------------------
# Translation Coverage Scan
# ---------------------------------------------------------------------------


def _translation_coverage_scan_wrapper():
    """Translation coverage scan (#232 nightly)."""
    start = time.time()
    try:
        from tools.consciousness.translation_scanners.orchestrator import (
            run_translation_coverage_scan,
        )

        summary = run_translation_coverage_scan()
        _log_cycle(
            "translation_coverage_scan",
            items_processed=summary.get("auto_fixed", 0),
            items_failed=0,
            duration_ms=summary.get("duration_ms", 0),
            details=summary,
        )
    except Exception as e:  # noqa: BLE001
        dur = int((time.time() - start) * 1000)
        logger.error("[TranslationScan] failed: %s", e)
        _log_cycle("translation_coverage_scan", 0, 1, dur, error_message=str(e))


def _probe_domain_visual_trigger_wrapper():
    """Fire Playwright visual scan delegate if recent domain translation gaps exist (03:30 UTC)."""
    try:
        from database import get_db_cursor
        from services.delegation_service import delegate_task

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """SELECT COUNT(*) AS n FROM translation_gaps
                   WHERE status IN ('open', 'routed')
                     AND source LIKE 'domain:%%'
                     AND created_at >= NOW() - INTERVAL '25 hours'"""
            )
            recent_gaps = cur.fetchone()["n"]

        if recent_gaps == 0:
            logger.info("[ProbeVisualTrigger] no recent domain gaps — skipping visual scan")
            return

        result = delegate_task(
            capability="visual_scan",
            reason=(
                f"P.R.O.B.E. domain translation audit found {recent_gaps} gap(s) "
                f"in last 25h. Trigger Playwright visual scan to confirm DOM rendering."
            ),
            args={"trigger": "translation_audit", "recent_gap_count": recent_gaps},
            delegation_source="automation",
            requested_by="probe_domain_audit",
            priority=5,
        )
        logger.info("[ProbeVisualTrigger] visual_scan delegated: %s", result)
        _log_cycle(
            "probe_domain_visual_trigger",
            items_processed=recent_gaps,
            items_failed=0,
            duration_ms=0,
            details=result,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[ProbeVisualTrigger] failed: %s", e)


def portrait_auto_approve():
    """Auto-approve completed portrait queue entries that haven't been linked yet.

    Runs every 60s. Finds media_generation_queue rows where:
      - status = 'completed'
      - owner_type = 'agent'
      - result_media_id IS NOT NULL
      - agent_portraits.canonical_image_path IS NULL for that agent

    Calls portrait_service.approve_canonical(agent_id, media_id) for each,
    which sets canonical_image_path, updates agents.avatar_url via agent_service,
    syncs website thumb, and pushes to Hostinger — completing the full pipeline
    without requiring manual approval in the Media Studio UI.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT q.id AS queue_id, q.owner_id AS agent_id, q.result_media_id
                FROM media_generation_queue q
                LEFT JOIN agent_portraits ap ON ap.agent_id = q.owner_id
                WHERE q.status = 'completed'
                  AND q.owner_type = 'agent'
                  AND q.result_media_id IS NOT NULL
                  AND (ap.canonical_image_path IS NULL OR ap.canonical_image_path = '')
                ORDER BY q.completed_at DESC
                LIMIT 10
                """
            )
            pending = cur.fetchall()
    except Exception:
        logger.exception("[PortraitAutoApprove] DB query failed")
        return

    if not pending:
        return

    from tools.media_studio.services.portrait_service import approve_canonical

    for row in pending:
        agent_id = row["agent_id"]
        media_id = row["result_media_id"]
        queue_id = row["queue_id"]
        try:
            result = approve_canonical(agent_id, media_id)
            if result.get("error"):
                logger.warning(
                    "[PortraitAutoApprove] approve_canonical failed agent=%d media=%d: %s",
                    agent_id,
                    media_id,
                    result["error"],
                )
            else:
                logger.info(
                    "[PortraitAutoApprove] agent=%d media=%d approved → avatar_url=%s",
                    agent_id,
                    media_id,
                    result.get("avatar_url"),
                )
        except Exception:
            logger.exception("[PortraitAutoApprove] exception for agent=%d media=%d", agent_id, media_id)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_fleet_jobs(scheduler, flask_app):
    """Register all fleet/infrastructure background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    def with_ctx(fn):
        """Wrap function to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn()

        wrapper.__name__ = fn.__name__
        return wrapper

    scheduler.add_job(
        with_ctx(check_fleet_health),
        trigger=IntervalTrigger(seconds=30),
        id="agent_fleet_health",
        name="Agent Loop: Fleet Health Monitor",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_mesh_health),
        trigger=IntervalTrigger(seconds=60),
        id="agent_mesh_health",
        name="Agent Loop: Mesh VPN Health Monitor",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(warmup_fleet_models),
        trigger=IntervalTrigger(minutes=20),
        id="fleet_model_warmup",
        name="Fleet Model Warmup — keep GPU+CPU sets loaded across all nodes",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(save_model_state),
        trigger=IntervalTrigger(minutes=5),
        id="agent_model_state_save",
        name="Agent Loop: Model State Persistence",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_standalone_health),
        trigger=IntervalTrigger(seconds=60),
        id="agent_standalone_health",
        name="Agent Loop: Standalone Health Monitor",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_vps_health),
        trigger=IntervalTrigger(minutes=5),
        id="agent_vps_health",
        name="Agent Loop: VPS Health Monitor",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_hub_containers),
        trigger=IntervalTrigger(minutes=5),
        id="agent_hub_containers",
        name="Agent Loop: Hub Container Observer",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(_translation_coverage_scan_wrapper),
        trigger=CronTrigger(hour=2, minute=0, timezone="America/Toronto"),
        id="translation_coverage_scan",
        name="Agent Loop: Translation Coverage Scan",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(_probe_domain_visual_trigger_wrapper),
        trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
        id="probe_domain_visual_trigger",
        name="Agent Loop: P.R.O.B.E. Domain Visual Scan Trigger",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(department_metrics_rollup),
        trigger=CronTrigger(hour=2, minute=0, timezone="America/Toronto"),
        id="department_metrics_rollup",
        name="Agent Loop: Department Metrics Rollup",
        replace_existing=True,
    )

    # DISABLED 2026-05-13: fleet_ssl_renewal paused — wildcard cert has 44 days remaining,
    # renewal fails daily due to 6 stale _acme-challenge TXT records causing DNS:4008.
    # Re-enable after invitation wizard ships and stale DNS records are cleared manually.
    # See task #2770 for full cleanup checklist.
    # scheduler.add_job(
    #     with_ctx(renew_fleet_ssl),
    #     trigger=CronTrigger(hour=3, minute=0, timezone="America/Toronto"),
    #     id="fleet_ssl_renewal",
    #     name="Agent Loop: Fleet SSL Renewal",
    #     replace_existing=True,
    # )

    scheduler.add_job(
        with_ctx(budget_reconciliation),
        trigger=IntervalTrigger(minutes=60),
        id="budget_reconciliation",
        name="Agent Loop: Budget Counter Reconciliation",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(portrait_auto_approve),
        trigger=IntervalTrigger(seconds=60),
        id="portrait_auto_approve",
        name="Agent Loop: Portrait Auto-Approve (Media Studio → agents.avatar_url)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
