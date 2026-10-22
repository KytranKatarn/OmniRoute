"""Queue tab data: one scope for the list AND the counters, wait-vs-run timing, and per-node GPU status.

Why this exists (Media Studio review 2026-10-21, task #7427):

* The Queue tab's counters came from ``batch_service.get_queue_stats("user", user_id)`` while its list merged user
  AND agent jobs. Nearly every job is an agent portrait (302 completed / 87 failed in the DB; the user owns none that
  completed), so the header read "0 active / 0 failed / 0 completed" above 51 listed rows. Both now use ONE scope.
* The card showed ``now - started_at`` for finished jobs, so a job that ran 40 seconds seven hours ago read
  "429m 55s". The API now returns ``wait_ms`` and ``run_ms`` separately.
* The "ComfyUI GPU queue" panel asked only the hub's ComfyUI, so it said "idle" while Defiant was generating.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_STATUSES = ("pending", "dispatched", "generating", "completed", "failed", "cancelled")
HUB_LABEL = "Starbase (hub)"


def parse_statuses(raw) -> List[str]:
    """``'failed,completed'`` -> ``['failed', 'completed']``; unknown values are dropped, never passed to SQL."""
    if not raw:
        return []
    seen: List[str] = []
    for part in str(raw).split(","):
        part = part.strip().lower()
        if part in VALID_STATUSES and part not in seen:
            seen.append(part)
    return seen


def _as_utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _ms(delta) -> Optional[int]:
    return None if delta is None else max(0, int(delta.total_seconds() * 1000))


def annotate_timing(row: Dict, now: Optional[datetime] = None) -> Dict:
    """Add ``wait_ms`` (queued -> started), ``run_ms`` (started -> finished), ``model`` and ``node``.

    A job still pending is waiting *so far*; one generating is running *so far*; a job that failed before it ever
    started has no run time at all (``None``), which is the truth rather than a misleading 0.
    """
    now = now or datetime.now(timezone.utc)
    created, started, done = (_as_utc(row.get(k)) for k in ("created_at", "started_at", "completed_at"))
    status = row.get("status")
    wait = run = None
    if created:
        if started:
            wait = _ms(started - created)
        elif status in ("pending", "dispatched"):
            wait = _ms(now - created)
    if started:
        if done:
            run = _ms(done - started)
        elif status == "generating":
            run = _ms(now - started)
    raw_params = row.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    out = dict(row)
    out.update(wait_ms=wait, run_ms=run, model=params.get("model"), node=params.get("fleet_node"))
    return out


def list_queue(user_id: int, statuses: List[str], limit: int, offset: int = 0, get_cursor=None) -> Dict:
    """Jobs the Queue tab shows: this user's jobs plus every agent job (the same scope as the counters).

    ``statuses`` empty means "any". The SQL is two literal statements (no interpolation); the scope is repeated
    on purpose so nothing is ever built by string formatting.
    """
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with get_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT COUNT(*) AS total
              FROM media_generation_queue q
             WHERE (q.owner_type = 'agent' OR (q.owner_type = 'user' AND q.owner_id = %s))
               AND (cardinality(%s::text[]) = 0 OR q.status = ANY(%s))
            """,
            (user_id, statuses, statuses),
        )
        total = int(cur.fetchone()["total"])
        cur.execute(
            """
            SELECT q.*, ml.thumbnail_path, ml.file_path,
                   CASE WHEN q.owner_type = 'agent' THEN a.display_name ELSE NULL END AS agent_name
              FROM media_generation_queue q
              LEFT JOIN media_library ml ON ml.id = q.result_media_id
              LEFT JOIN agents a ON a.id = q.owner_id AND q.owner_type = 'agent'
             WHERE (q.owner_type = 'agent' OR (q.owner_type = 'user' AND q.owner_id = %s))
               AND (cardinality(%s::text[]) = 0 OR q.status = ANY(%s))
             ORDER BY q.created_at DESC
             LIMIT %s OFFSET %s
            """,
            (user_id, statuses, statuses, limit, offset),
        )
        rows = [annotate_timing(dict(r)) for r in cur.fetchall()]
    return {"items": rows, "total": total}


def get_overview(user_id: int, get_cursor=None) -> Dict:
    """Counters for the header, in the SAME scope as :func:`list_queue`.

    ``completed`` / ``failed`` stay all-time (back-compat with the old keys); the ``_24h`` variants are what the tab
    should headline, because an all-time failure count of 92 reads as an alarm when most are from earlier tests.
    """
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    with get_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('pending', 'dispatched')) AS pending,
                COUNT(*) FILTER (WHERE status = 'generating') AS running,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (
                    WHERE status = 'completed' AND completed_at > NOW() - INTERVAL '24 hours'
                ) AS completed_24h,
                COUNT(*) FILTER (
                    WHERE status = 'failed' AND COALESCE(completed_at, created_at) > NOW() - INTERVAL '24 hours'
                ) AS failed_24h,
                AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000)
                    FILTER (WHERE status = 'completed' AND started_at IS NOT NULL) AS avg_run_ms,
                AVG(EXTRACT(EPOCH FROM (started_at - created_at)) * 1000)
                    FILTER (WHERE status = 'completed' AND started_at IS NOT NULL) AS avg_wait_ms
            FROM media_generation_queue
            WHERE owner_type = 'agent' OR (owner_type = 'user' AND owner_id = %s)
            """,
            (user_id,),
        )
        row = dict(cur.fetchone())
    for key in ("avg_run_ms", "avg_wait_ms"):
        row[key] = int(round(float(row.get(key) or 0)))
    row["avg_duration_ms"] = row["avg_run_ms"]  # legacy key
    return {k: (int(v) if v is not None else 0) for k, v in row.items()}


# --- per-node GPU status ----------------------------------------------------------------------------------------


def _fetch_comfy_queue(url: str, timeout: float = 3.0) -> Dict:
    import requests

    data = requests.get(f"{url}/queue", timeout=timeout).json()
    return {"running": len(data.get("queue_running", [])), "pending": len(data.get("queue_pending", []))}


def comfyui_nodes(get_cursor=None) -> List[Dict]:
    """Every ComfyUI the platform can use: the online fleet nodes that advertise one, plus the hub's."""
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    nodes: List[Dict] = []
    try:
        with get_cursor() as (_conn, cur):
            cur.execute(
                "SELECT node_name, extra_capabilities->>'comfyui_url' AS url FROM remote_nodes "
                "WHERE status = 'online' AND extra_capabilities->>'comfyui_url' IS NOT NULL ORDER BY node_name"
            )
            nodes = [{"name": r["node_name"], "url": r["url"], "hub": False} for r in cur.fetchall()]
    except Exception as exc:  # a DB hiccup must not blank the panel: the hub is still listed below
        logger.warning("comfyui_nodes: remote_nodes lookup failed: %s", exc)
    hub_url = os.environ.get("COMFYUI_HOST", "http://archie_comfyui:8188")
    nodes.append({"name": HUB_LABEL, "url": hub_url, "hub": True})
    return nodes


def gpu_nodes_status(
    nodes: Optional[List[Dict]] = None,
    leases: Optional[List[Dict]] = None,
    fetch: Callable[[str], Dict] = _fetch_comfy_queue,
) -> Dict:
    """Queue depth per GPU node plus who holds its image lease. Nodes are asked in parallel with a short timeout.

    An unreachable *hub* ComfyUI is normal (it is stopped when idle and started on demand), so it reads ``idle``;
    an unreachable *fleet node* reads ``unreachable``.
    """
    if nodes is None:
        nodes = comfyui_nodes()
    if leases is None:
        from services.node_gpu_lease import active_leases

        leases = active_leases()
    holders = {(l.get("node_name") or ""): l.get("holder") for l in leases}

    def one(node):
        entry = {"name": node["name"], "hub": bool(node.get("hub")), "running": 0, "pending": 0}
        try:
            entry.update(fetch(node["url"]))
            entry["state"] = "busy" if (entry["running"] or entry["pending"]) else "idle"
        except Exception as exc:
            entry["state"] = "idle" if node.get("hub") else "unreachable"
            entry["note"] = "stopped (starts on demand)" if node.get("hub") else str(exc)[:80]
        entry["lease_holder"] = next(
            (h for n, h in holders.items() if n == node["name"] or (node.get("hub") and n.startswith("Starbase"))),
            None,
        )
        return entry

    with ThreadPoolExecutor(max_workers=max(1, len(nodes))) as pool:
        entries = list(pool.map(one, nodes))
    return {
        "nodes": entries,
        "running": sum(e["running"] for e in entries),
        "pending": sum(e["pending"] for e in entries),
    }
