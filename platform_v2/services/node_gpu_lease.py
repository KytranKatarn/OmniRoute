"""Per-node GPU lease shared by Media Studio image sessions and the LLM dispatcher (#7401).

An image session on a fleet node (e.g. Starship Defiant, 8GB) holds a lease while its SDXL checkpoint is
resident. When ``dispatch:gpu_lease:enabled`` is true, LLM dispatch skips leased nodes (hub fallback), so an
LLM load can no longer evict SDXL mid-session.

* Acquisition ALWAYS records the lease (cheap, and it makes contention visible); only ENFORCEMENT is flagged.
* ``leased_node_db_ids()`` is empty when the flag is off, so every call site is byte-identical to before
  until the flag is turned on.
* Everything FAILS OPEN: a missing table, DB error or bad setting means "no lease", never a blocked dispatch.
* A lease whose heartbeat is older than ``dispatch:gpu_lease:ttl_s`` (default 180) is treated as dead, so a
  killed worker can never hold a node past the TTL.
"""

import logging
import time
from typing import Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

SETTING_ENABLED = "dispatch:gpu_lease:enabled"
SETTING_TTL_S = "dispatch:gpu_lease:ttl_s"
DEFAULT_TTL_S = 180

_ENABLED_CACHE_S = 15.0
_IDS_CACHE_S = 5.0
_cache: Dict[str, tuple] = {}


def _setting(key: str, default):
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return default
        val = row.get("value") if isinstance(row, dict) else row[0]
        return default if val is None else val
    except Exception:
        return default


def _ttl_s() -> int:
    try:
        return max(30, min(1800, int(_setting(SETTING_TTL_S, DEFAULT_TTL_S))))
    except (TypeError, ValueError):
        return DEFAULT_TTL_S


def _cached(key: str, ttl: float, compute, clock=time.monotonic):
    now = clock()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = compute()
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()


def enforcement_enabled() -> bool:
    """Default OFF. Only the strings true/1/yes/on (any case) enable it; anything else is off."""
    return _cached(
        "enabled",
        _ENABLED_CACHE_S,
        lambda: str(_setting(SETTING_ENABLED, "false")).strip().lower() in ("true", "1", "yes", "on"),
    )


def acquire(node_name: str, holder: str, kind: str = "image", get_cursor=None) -> bool:
    """Take (or refresh) the lease. True if ``holder`` now owns it; False if another LIVE holder does."""
    if not node_name:
        return False
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    try:
        with get_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO node_gpu_leases (node_name, holder, holder_kind, acquired_at, heartbeat_at)
                VALUES (%(node)s, %(holder)s, %(kind)s, NOW(), NOW())
                ON CONFLICT (node_name) DO UPDATE
                   SET holder = EXCLUDED.holder,
                       holder_kind = EXCLUDED.holder_kind,
                       heartbeat_at = NOW(),
                       acquired_at = CASE WHEN node_gpu_leases.holder = EXCLUDED.holder
                                          THEN node_gpu_leases.acquired_at ELSE NOW() END
                 WHERE node_gpu_leases.holder = EXCLUDED.holder
                    OR node_gpu_leases.heartbeat_at < NOW() - make_interval(secs => %(ttl)s)
                RETURNING node_name
                """,
                {"node": node_name, "holder": holder, "kind": kind, "ttl": _ttl_s()},
            )
            return bool(cur.fetchone())
    except Exception as exc:
        logger.warning("[GpuLease] acquire failed for %s (fail-open): %s", node_name, exc)
        return False


def heartbeat(node_name: str, holder: str, get_cursor=None) -> bool:
    """Refresh a lease this holder ALREADY owns. UPDATE-only: it never creates or re-creates a lease.

    The heartbeat thread can fire just after a session closed and released; as an upsert (the same SQL as
    ``acquire``) that late pulse re-inserted the row and left an orphan lease holding the node for the whole TTL.
    """
    if not node_name:
        return False
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    try:
        with get_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE node_gpu_leases SET heartbeat_at = NOW() WHERE node_name = %s AND holder = %s "
                "RETURNING node_name",
                (node_name, holder),
            )
            return bool(cur.fetchone())
    except Exception as exc:
        logger.warning("[GpuLease] heartbeat failed for %s (fail-open): %s", node_name, exc)
        return False


def release(node_name: str, holder: str, get_cursor=None) -> bool:
    """Drop the lease if ``holder`` still owns it (never another holder's)."""
    if not node_name:
        return False
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    try:
        with get_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "DELETE FROM node_gpu_leases WHERE node_name = %s AND holder = %s RETURNING node_name",
                (node_name, holder),
            )
            return bool(cur.fetchone())
    except Exception as exc:
        logger.warning("[GpuLease] release failed for %s: %s", node_name, exc)
        return False


def active_leases(get_cursor=None) -> List[dict]:
    """Live leases for visibility (NOT gated by the enforcement flag)."""
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    try:
        with get_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT node_name, holder, holder_kind, acquired_at, heartbeat_at
                  FROM node_gpu_leases
                 WHERE heartbeat_at > NOW() - make_interval(secs => %s)
                 ORDER BY node_name
                """,
                (_ttl_s(),),
            )
            return [dict(r) for r in (cur.fetchall() or [])]
    except Exception:
        return []


def leased_node_db_ids(get_cursor=None) -> FrozenSet[int]:
    """remote_nodes.id of every node an LLM must currently stay off. EMPTY when enforcement is off."""
    if not enforcement_enabled():
        return frozenset()

    def compute() -> FrozenSet[int]:
        cursor_fn = get_cursor
        if cursor_fn is None:
            from database import get_db_cursor as cursor_fn
        try:
            with cursor_fn() as (_conn, cur):
                cur.execute(
                    """
                    SELECT rn.id
                      FROM node_gpu_leases l
                      JOIN remote_nodes rn ON rn.node_name = l.node_name
                     WHERE l.heartbeat_at > NOW() - make_interval(secs => %s)
                    """,
                    (_ttl_s(),),
                )
                rows = cur.fetchall() or []
            return frozenset(int(r["id"] if isinstance(r, dict) else r[0]) for r in rows)
        except Exception:
            return frozenset()

    return _cached("ids", _IDS_CACHE_S, compute)


def is_node_leased(node_db_id: Optional[int]) -> bool:
    """True when this node (remote_nodes.id) is leased AND enforcement is on. Fail-open False."""
    try:
        return node_db_id is not None and int(node_db_id) in leased_node_db_ids()
    except Exception:
        return False
