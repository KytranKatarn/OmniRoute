"""Shared C.R.E.E.D. event emitter with per-product tenant routing (#3958).

Every governance event routes to the C.R.E.E.D. tenant of the EMITTING AGENT
(spec KB #272124/#272125): agents.creed_tenant slug -> per-product ingest key
CREED_INGEST_KEY_<PRODUCT> -> Bearer auth picks the tenant at the creed side.
NULL/unknown agents default to the core-platform tenant 'kytran-empowerment'.

Replaces the scattered single-tenant CREED_INGEST_KEY pushes in
bias_sampling_service, carbon_footprint_service, incident_service and the
agent_loop governance reporter.

Key fallback chain (never lose an event to a missing env var):
  tenant key -> kytran-empowerment key -> legacy CREED_INGEST_KEY.
Works from both the platform container and the scheduler sidecar (self-
contained psycopg2 lookup; no platform_v2.database import required).
"""

import logging
import os
import threading
import time

import psycopg2
import requests

logger = logging.getLogger(__name__)

DEFAULT_TENANT = "kytran-empowerment"
_CREED_URL = os.getenv("CREED_INGEST_URL", "http://kytran_creed:8086")
_CACHE_TTL = 300  # seconds; agent->tenant assignments change rarely

_cache_lock = threading.Lock()
_tenant_cache: dict = (
    {}
)  # key: ("id", 42) or ("name", "B.I.A.S.") -> (slug, expires_at)
_warned_missing_keys: set = set()


def _env_var_for(slug: str) -> str:
    return "CREED_INGEST_KEY_" + slug.upper().replace("-", "_")


def _db_password() -> str:
    """Docker secret file first, env fallback — mirrors database._get_db_password()."""
    secret_file = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
    try:
        with open(secret_file) as f:
            return f.read().strip()
    except OSError:
        return os.getenv("DB_PASSWORD", "")


def _db_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_db_password(),
        connect_timeout=5,
    )


def _lookup_tenant(agent_id=None, agent_name=None) -> str:
    """One-row lookup of agents.creed_tenant; NULL/missing -> default."""
    conn = None
    try:
        conn = _db_conn()
        cur = conn.cursor()
        if agent_id is not None:
            cur.execute(
                "SELECT creed_tenant FROM agents WHERE id = %s", (int(agent_id),)
            )
        else:
            cur.execute(
                "SELECT creed_tenant FROM agents WHERE name = %s LIMIT 1", (agent_name,)
            )
        row = cur.fetchone()
        return (row[0] or DEFAULT_TENANT) if row else DEFAULT_TENANT
    except Exception as exc:  # never let routing kill the caller
        logger.warning("creed_emit: tenant lookup failed (%s) — using default", exc)
        return DEFAULT_TENANT
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()


def resolve_tenant(agent_id=None, agent_name=None) -> str:
    """Resolve the C.R.E.E.D. tenant slug for an agent (TTL-cached)."""
    if agent_id is not None:
        try:
            cache_key = ("id", int(agent_id))
        except (TypeError, ValueError):
            cache_key = None
            agent_id = None
    else:
        cache_key = ("name", agent_name) if agent_name else None
    if cache_key is None:
        return DEFAULT_TENANT

    now = time.monotonic()
    with _cache_lock:
        hit = _tenant_cache.get(cache_key)
        if hit and hit[1] > now:
            return hit[0]

    slug = _lookup_tenant(agent_id=agent_id, agent_name=agent_name)
    with _cache_lock:
        _tenant_cache[cache_key] = (slug, now + _CACHE_TTL)
    return slug


def invalidate_cache() -> None:
    """Drop the agent->tenant cache (call after editing creed_tenant values)."""
    with _cache_lock:
        _tenant_cache.clear()


def key_for_tenant(slug: str) -> tuple[str, str]:
    """Return (key, effective_slug). Fallback: tenant -> default -> legacy."""
    key = os.getenv(_env_var_for(slug), "")
    if key:
        return key, slug
    if slug != DEFAULT_TENANT:
        if slug not in _warned_missing_keys:
            _warned_missing_keys.add(slug)
            logger.warning(
                "creed_emit: %s not set — events for tenant '%s' fall back to %s",
                _env_var_for(slug),
                slug,
                DEFAULT_TENANT,
            )
        key = os.getenv(_env_var_for(DEFAULT_TENANT), "")
        if key:
            return key, DEFAULT_TENANT
    legacy = os.getenv("CREED_INGEST_KEY", "")
    if legacy and DEFAULT_TENANT not in _warned_missing_keys:
        _warned_missing_keys.add(DEFAULT_TENANT)
        logger.warning(
            "creed_emit: %s not set — falling back to legacy CREED_INGEST_KEY",
            _env_var_for(DEFAULT_TENANT),
        )
    return legacy, "legacy"


def auth_header_for_agent(agent_id=None, agent_name=None) -> dict:
    """Authorization header routed to the agent's tenant (e.g. incidents API)."""
    key, _ = key_for_tenant(resolve_tenant(agent_id=agent_id, agent_name=agent_name))
    return {"Authorization": f"Bearer {key}"} if key else {}


def emit_event(
    category: str,
    severity: str,
    description: str,
    event_type: str = "agent_action",
    agent_id=None,
    agent_name: str = None,
    module: str = None,
    metadata: dict = None,
    timeout: int = 5,
) -> bool:
    """Push one governance event to C.R.E.E.D., routed to the agent's tenant.

    module: core-platform drill-down tag (Backup/Security/EmailManager/...)
    per spec KB #272125 — carried in metadata, set by module-owning callers.
    Returns True on 200/201; never raises.
    """
    slug = resolve_tenant(agent_id=agent_id, agent_name=agent_name)
    key, effective = key_for_tenant(slug)
    if not key:
        logger.info(
            "creed_emit: no ingest key available — skipping event (%s/%s)",
            category,
            event_type,
        )
        return False

    meta = dict(metadata or {})
    if module:
        meta["module"] = module
    meta.setdefault("routed_tenant", slug)

    payload = {
        "event_type": event_type,
        "source_platform": "archie_platform",
        "agent_id": str(agent_id) if agent_id is not None else (agent_name or "system"),
        "agent_name": agent_name or "System",
        "category": category,
        "severity": severity,
        "description": description,
        "metadata": meta,
    }
    try:
        resp = requests.post(
            f"{_CREED_URL}/api/v1/events",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning(
            "creed_emit: push rejected %s (tenant=%s via %s): %s",
            resp.status_code,
            slug,
            effective,
            resp.text[:200],
        )
        return False
    except requests.RequestException as exc:
        logger.warning("creed_emit: push failed (tenant=%s): %s", slug, exc)
        return False
