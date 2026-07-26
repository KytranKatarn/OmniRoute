"""Living Platform Registry — collector (task #5230, Phase 1).

WHAT THIS REPLACES
`.claude/rules/module-capability-index.md` is 314 hand-typed lines that every new
session reads FIRST and then acts on. Hand-maintained documentation does not just
go stale — it asserts false things that agents believe *because they are written
down*: two phantom tables that left backups unmonitored while appearing monitored,
three modules listed as Codex-writable that never were, `auth_events` documented
as existing when it does not.

So: collect from the live source (`module_registry.MODULES`, a list of
`ModuleDefinition` dataclasses) instead of from prose.

TWO RULES THAT SHAPE EVERYTHING HERE
--------------------------------------
1. **`notes` is human-owned and the collector must never write it.** The valuable
   half of the old index is the hand-written rationale ("SABnzbd `set_config` is
   unreliable — edit sabnzbd.ini directly"). That cannot be derived. If a regen
   wiped it, everyone would go straight back to hand-editing the markdown and the
   whole exercise would be worse than useless.

2. **Nothing is ever deleted.** A module that disappears gets `status='absent'`
   with `last_seen_at` frozen. A disappearance is the single most interesting
   event this table can record — deleting the row erases exactly the evidence.
   Same rule as the backup-freshness and gov-watch ingest monitors: absence is a
   finding, not a cleanup.

WHY IT READS THE MODULE OBJECTS AND NOT THE FILE TEXT
Parsing `module_registry.py` as text would be a second implementation of Python
that drifts from the real one. Importing it means the registry is whatever the
app actually loads — if the import breaks, collection fails loudly rather than
reporting a confident wrong answer.
"""

from __future__ import annotations

import json
import os
import logging
from typing import Any

from database import get_db_cursor
from services.time_utils import now_utc

logger = logging.getLogger(__name__)

# Columns the collector owns. `notes` is deliberately ABSENT — see rule 1.
_COLLECTED = (
    "name",
    "description",
    "category",
    "route",
    "blueprint_import",
    "external_url",
    "required_permissions",
    "minimum_role",
    "minimum_tier",
    "enabled",
    "beta",
    "coming_soon",
    "version",
    "tags",
    "show_on_dashboard",
)


def collect_modules() -> list[dict[str, Any]]:
    """Read the LIVE module registry. Raises if it cannot be imported.

    Deliberately not fail-soft: a collector that returns [] on ImportError would
    mark every module 'absent' and render an empty index — a confident wrong
    answer, which is the exact failure mode this task exists to remove.
    """
    import module_registry as mr

    out: list[dict[str, Any]] = []
    for m in mr.MODULES:
        category = m.category.value if hasattr(m.category, "value") else str(m.category)
        out.append(
            {
                "module_id": m.id,
                "name": m.name,
                # The registry stores descriptions with <br> for the dashboard.
                "description": (m.description or "").replace("<br>", " · ").strip(),
                "category": category,
                "route": m.route or None,
                "blueprint_import": m.blueprint_import or None,
                "external_url": m.external_url or None,
                "required_permissions": list(m.required_permissions or []),
                "minimum_role": m.minimum_role,
                "minimum_tier": m.minimum_tier,
                "enabled": bool(m.enabled),
                "beta": bool(getattr(m, "beta", False)),
                "coming_soon": bool(getattr(m, "coming_soon", False)),
                "version": getattr(m, "version", None),
                "tags": list(getattr(m, "tags", []) or []),
                "show_on_dashboard": bool(getattr(m, "show_on_dashboard", True)),
            }
        )
    return out


def reconcile(modules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Upsert collected modules; mark anything no longer present as absent.

    Returns a summary: {collected, inserted, updated, absent, reappeared}.
    NEVER deletes a row.
    """
    modules = collect_modules() if modules is None else modules
    if not modules:
        # Cannot happen via collect_modules (it raises), but a caller could pass
        # []. Refuse rather than mark the entire platform absent.
        raise ValueError("refusing to reconcile an empty module set — that would mark every module absent")

    seen = {m["module_id"] for m in modules}
    now = now_utc()
    summary = {"collected": len(modules), "inserted": 0, "updated": 0, "absent": 0, "reappeared": 0}

    cols = ", ".join(_COLLECTED)
    placeholders = ", ".join(["%s"] * len(_COLLECTED))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLLECTED)

    with get_db_cursor(commit=True) as (_conn, cur):
        before = _snapshot(cur, "module")
        cur.execute("SELECT module_id, status FROM platform_registry_module")
        existing = {
            r["module_id"] if isinstance(r, dict) else r[0]: (r["status"] if isinstance(r, dict) else r[1])
            for r in cur.fetchall()
        }

        for m in modules:
            values = []
            for c in _COLLECTED:
                v = m[c]
                values.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
            cur.execute(
                f"""
                INSERT INTO platform_registry_module (module_id, {cols}, status, first_seen_at, last_seen_at, collected_at)
                VALUES (%s, {placeholders}, 'present', %s, %s, %s)
                ON CONFLICT (module_id) DO UPDATE SET
                    {updates},
                    status       = 'present',
                    last_seen_at = EXCLUDED.last_seen_at,
                    collected_at = EXCLUDED.collected_at
                """,
                # notes is not in the column list, so ON CONFLICT cannot touch it.
                [m["module_id"], *values, now, now, now],
            )
            prior = existing.get(m["module_id"])
            if prior is None:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
                if prior == "absent":
                    summary["reappeared"] += 1

        # Absent: previously collected, not in this run. last_seen_at is NOT
        # touched — freezing it is the whole point, it answers "when did it go?"
        gone = [mid for mid, st in existing.items() if mid not in seen and st != "absent"]
        if gone:
            cur.execute(
                "UPDATE platform_registry_module SET status='absent', collected_at=%s WHERE module_id = ANY(%s)",
                (now, gone),
            )
            summary["absent"] = len(gone)
            logger.warning("platform_registry: %d module(s) went absent: %s", len(gone), ", ".join(sorted(gone)))

        summary["changes"] = _emit_changes(cur, "module", before, _snapshot(cur, "module"))

    return summary


def get_modules(include_absent: bool = True) -> list[dict[str, Any]]:
    """Read the registry back, notes included, ordered for rendering."""
    sql = """
        SELECT * FROM platform_registry_module
        {where}
        ORDER BY category, (NOT enabled), module_id
    """.format(
        where="" if include_absent else "WHERE status = 'present'"
    )
    with get_db_cursor() as (_conn, cur):
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def set_notes(module_id: str, notes: str | None) -> bool:
    """Set the human-owned notes for a module. The only writer of that column."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE platform_registry_module SET notes = %s WHERE module_id = %s",
            (notes, module_id),
        )
        return cur.rowcount > 0


def registry_summary() -> dict[str, Any]:
    """Counts for the generated header — including freshness, so the document
    can DECLARE ITS OWN STALENESS rather than implying it is current."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'present')            AS present,
                   count(*) FILTER (WHERE status = 'absent')             AS absent,
                   count(*) FILTER (WHERE status = 'present' AND enabled) AS enabled,
                   count(*) FILTER (WHERE notes IS NOT NULL AND notes <> '') AS with_notes,
                   max(collected_at)                                     AS collected_at
            FROM platform_registry_module
            """
        )
        row = cur.fetchone()
        return dict(row) if isinstance(row, dict) else {}


# ============================================================================
# PHASE 2 — services (task #5230)
#
# Two live sources answering two different questions:
#   DOCKER     — what is actually running on the hub right now.
#   PROVENANCE — for the 9 image-baked products, does the RUNNING image match the
#                source it claims? Delegated to scripts/deploy_drift_check.py
#                check_products(), already the provenance SSOT (the daily
#                deploy_drift_monitor job, the F.O.R.G.E. Dockerfile guard and the
#                Repair Bay tab all read it). A second drift checker here would
#                create precisely the divergence this registry exists to remove.
# ============================================================================

_SERVICE_COLLECTED = (
    "kind",
    "host",
    "container_name",
    "image",
    "container_state",
    "restart_policy",
    "compose_project",
    "compose_service",
    "ports",
    "started_at",
    "version_url",
)
# Provenance columns are written ONLY when provenance was actually measured, so a
# cheap container-only run cannot stamp a stale reading as fresh.
_PROVENANCE_COLLECTED = ("baked_sha", "expected_sha", "drift_status", "provenance_at")

_DRIFT_CHECK_PATH = "/mnt/archie_brain/scripts/deploy_drift_check.py"


def _load_drift_module():
    """Import deploy_drift_check.py by path — it is a script, not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("deploy_drift_check", _DRIFT_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_DRIFT_CHECK_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collect_containers() -> list[dict[str, Any]]:
    """Enumerate REAL hub services from the docker daemon.

    THE FILTER MATTERS. `docker ps -a` on this host also returns throwaway
    `--rm` containers — the test suite spawns them constantly. Recording those
    would create rows that are marked absent seconds later, burying genuine
    disappearances in noise.

    A real service is: compose-managed OR carrying a restart policy. Verified
    2026-07-26 — `archie_hub_caddy` and `media_samba` are run with plain
    `docker run` (no compose label) but `restart=unless-stopped`, so filtering on
    the compose label alone would silently DROP two live services; a throwaway
    probe had neither label nor restart policy. Both halves of the OR are
    load-bearing.

    Raises if the daemon is unreachable — the caller must not mistake "I could
    not look" for "nothing is running".
    """
    import docker

    client = docker.from_env()
    out: list[dict[str, Any]] = []
    for c in client.containers.list(all=True):
        labels = c.labels or {}
        project = labels.get("com.docker.compose.project") or None
        policy = ((c.attrs.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or ""
        if not project and policy in ("", "no"):
            continue  # transient / throwaway — not a service

        ports = sorted(
            {
                f"{b.get('HostPort')}->{internal}"
                for internal, binds in ((c.attrs.get("NetworkSettings") or {}).get("Ports") or {}).items()
                for b in (binds or [])
                if b.get("HostPort")
            }
        )
        out.append(
            {
                "service_key": c.name,
                "kind": "container",
                "host": "hub",
                "container_name": c.name,
                "image": (c.image.tags[0] if getattr(c.image, "tags", None) else str(c.image.id)[:19]),
                "container_state": c.status,
                "restart_policy": policy or None,
                "compose_project": project,
                "compose_service": labels.get("com.docker.compose.service") or None,
                "ports": ports,
                "started_at": (c.attrs.get("State") or {}).get("StartedAt") or None,
                "version_url": None,
            }
        )
    return out


def collect_products(with_provenance: bool = False) -> list[dict[str, Any]]:
    """The 9 image-baked products, optionally with a fresh drift measurement.

    with_provenance is OFF by default because check_products() makes a GitHub API
    call plus an HTTP fetch per product — fine for a nightly job, far too slow to
    pay on every collection. When it is off the provenance columns are left
    ENTIRELY UNTOUCHED rather than nulled: wiping a real reading because this
    particular run was cheap would destroy information, and writing provenance_at
    would date a measurement that never happened.
    """
    drift = _load_drift_module()

    measured: dict[str, dict] = {}
    if with_provenance:
        for r in drift.check_products():
            measured[r["product"]] = r

    now = now_utc()
    out: list[dict[str, Any]] = []
    for key, meta in drift.PRODUCTS.items():
        url = meta.get("url") or ""
        # host is derived from the URL the drift checker actually probes, so it
        # cannot disagree with reality the way a hand-typed table does.
        host = url.split("//", 1)[-1].split(":", 1)[0] if "//" in url else None
        row = {
            "service_key": key,
            "kind": "product",
            "host": host,
            "container_name": None,
            "image": None,
            "container_state": None,
            "restart_policy": None,
            "compose_project": None,
            "compose_service": None,
            "ports": [],
            "started_at": None,
            "version_url": url or None,
        }
        if key in measured:
            m = measured[key]
            row.update(
                {
                    "baked_sha": m.get("baked_sha"),
                    "expected_sha": m.get("expected_sha"),
                    # 'fail_open' is an UNKNOWN (unreachable / no resolvable SHA),
                    # never a fault. Preserved verbatim from the SSOT.
                    "drift_status": m.get("status"),
                    "provenance_at": now,
                }
            )
        out.append(row)
    return out


def reconcile_services(with_provenance: bool = False) -> dict[str, Any]:
    """Collect services and reconcile. Returns a per-scope summary.

    SCOPED ABSENCE — the important bit. Each source is collected independently and
    either one can fail (the docker socket may be absent inside a test container;
    deploy_drift_check may not be mounted). A scope that FAILED to collect must
    NOT mark its rows absent: "I could not look" is not "it is gone". Marking
    every container absent because the socket was missing would manufacture a
    fleet-wide outage out of a permissions problem — the same shape as the
    empty-module-set guard in phase 1, applied per scope.
    """
    rows: list[dict[str, Any]] = []
    scopes: dict[str, bool] = {}
    errors: dict[str, str] = {}

    for kind, fn in (("container", collect_containers), ("product", lambda: collect_products(with_provenance))):
        try:
            got = fn()
            if not got:
                # A source that returns nothing is treated as NOT collected. An
                # empty docker daemon is not a real state on this host.
                raise ValueError(f"{kind} collection returned no rows")
            rows.extend(got)
            scopes[kind] = True
        except Exception as exc:  # noqa: BLE001 - any failure means "did not look"
            scopes[kind] = False
            errors[kind] = f"{type(exc).__name__}: {exc}"
            logger.warning("platform_registry: %s scope NOT collected (%s) — absence check skipped", kind, exc)

    if not rows:
        raise RuntimeError(f"no service scope could be collected: {errors}")

    now = now_utc()
    summary = {
        "collected": len(rows),
        "inserted": 0,
        "updated": 0,
        "absent": 0,
        "reappeared": 0,
        "scopes": scopes,
        "errors": errors,
        "provenance": with_provenance,
    }

    with get_db_cursor(commit=True) as (_conn, cur):
        before = _snapshot(cur, "service")
        cur.execute("SELECT service_key, kind, status FROM platform_registry_service")
        existing = {
            (r["service_key"] if isinstance(r, dict) else r[0]): (
                (r["kind"] if isinstance(r, dict) else r[1]),
                (r["status"] if isinstance(r, dict) else r[2]),
            )
            for r in cur.fetchall()
        }

        for row in rows:
            cols = list(_SERVICE_COLLECTED)
            if "drift_status" in row:  # provenance measured for this row
                cols += list(_PROVENANCE_COLLECTED)
            values = [json.dumps(row[c]) if isinstance(row.get(c), (list, dict)) else row.get(c) for c in cols]
            collist = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(cols))
            updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            cur.execute(
                f"""
                INSERT INTO platform_registry_service
                    (service_key, {collist}, status, first_seen_at, last_seen_at, collected_at)
                VALUES (%s, {placeholders}, 'present', %s, %s, %s)
                ON CONFLICT (service_key) DO UPDATE SET
                    {updates},
                    status       = 'present',
                    last_seen_at = EXCLUDED.last_seen_at,
                    collected_at = EXCLUDED.collected_at
                """,
                # `notes` is absent from every column list, so ON CONFLICT cannot reach it.
                [row["service_key"], *values, now, now, now],
            )
            prior = existing.get(row["service_key"])
            if prior is None:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
                if prior[1] == "absent":
                    summary["reappeared"] += 1

        seen = {r["service_key"] for r in rows}
        gone = [
            key
            for key, (kind, st) in existing.items()
            if key not in seen and st != "absent" and scopes.get(kind)  # ONLY within a collected scope
        ]
        if gone:
            cur.execute(
                "UPDATE platform_registry_service SET status='absent', collected_at=%s WHERE service_key = ANY(%s)",
                (now, gone),
            )
            summary["absent"] = len(gone)
            logger.warning("platform_registry: %d service(s) went absent: %s", len(gone), ", ".join(sorted(gone)))

        summary["changes"] = _emit_changes(cur, "service", before, _snapshot(cur, "service"))

    return summary


def get_services(include_absent: bool = True) -> list[dict[str, Any]]:
    where = "" if include_absent else "WHERE status = 'present'"
    with get_db_cursor() as (_conn, cur):
        cur.execute(f"SELECT * FROM platform_registry_service {where} ORDER BY kind, service_key")
        return [dict(r) for r in cur.fetchall()]


def set_service_notes(service_key: str, notes: str | None) -> bool:
    """The only writer of platform_registry_service.notes."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE platform_registry_service SET notes = %s WHERE service_key = %s",
            (notes, service_key),
        )
        return cur.rowcount > 0


# ============================================================================
# PHASE 3 — skills / commands / capabilities  (task #5230)
#
# The three things an agent can actually INVOKE. All read from live sources:
# the skill files on disk and CAPABILITY_DEPARTMENT_MAP in code. `learned-skills.md`
# is already generated by a Consciousness job, but the .claude/ surface — the one
# a session loads at boot — had no generator at all.
# ============================================================================

_REPO_ROOT = os.environ.get("ARCHIE_REPO_ROOT", "/mnt/archie_brain")


def _frontmatter(path: str) -> dict[str, str]:
    """Parse the leading YAML block. Deliberately tiny — name/description only.

    Not using a YAML library: the frontmatter is two flat scalars, and pulling a
    parser in would make the collector fail on a file with exotic-but-irrelevant
    YAML elsewhere in it.
    """
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
            if first.strip() != "---":
                return out
            for line in fh:
                if line.strip() == "---":
                    break
                if ":" in line:
                    k, _, v = line.partition(":")
                    out[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return out


def collect_skills() -> list[dict[str, Any]]:
    """Skills, slash-commands and dispatch capabilities, from disk + code.

    Raises if the .claude tree is missing — "I could not look" must not read as
    "there are no skills".
    """
    import glob

    rows: list[dict[str, Any]] = []
    scopes: dict[str, bool] = {}

    skills_root = os.path.join(_REPO_ROOT, ".claude", "skills")
    cmds_root = os.path.join(_REPO_ROOT, ".claude", "commands")

    # SCOPE HONESTY. The first run of this collector returned 0 commands and
    # reported success — the container's bind-mount exposes .claude/rules and
    # .claude/skills but NOT .claude/commands, so 18 real commands silently
    # became "none". That is the exact failure this whole task exists to remove:
    # an absence rendered as a clean result. A missing source root is now an
    # UNCOLLECTED SCOPE, which (per the phase-2 rule) reports itself and blocks
    # its own absence-marking, rather than quietly reading as zero.
    scopes["skill"] = os.path.isdir(skills_root)
    scopes["command"] = os.path.isdir(cmds_root)
    if not any(scopes.values()):
        raise FileNotFoundError(f"no .claude skill/command tree under {_REPO_ROOT}")
    for kind, ok in scopes.items():
        if not ok:
            logger.warning(
                "platform_registry: .claude/%ss missing under %s — scope NOT collected "
                "(rows will NOT be marked absent)",
                kind,
                _REPO_ROOT,
            )

    for p in sorted(glob.glob(os.path.join(skills_root, "**", "SKILL.md"), recursive=True)):
        fm = _frontmatter(p)
        name = fm.get("name") or os.path.basename(os.path.dirname(p))
        rows.append(
            {
                "skill_key": f"skill:{name}",
                "kind": "skill",
                "name": name,
                "description": fm.get("description"),
                "source_path": os.path.relpath(p, _REPO_ROOT),
                "department": None,
            }
        )

    for p in sorted(glob.glob(os.path.join(cmds_root, "*.md"))):
        name = os.path.splitext(os.path.basename(p))[0]
        fm = _frontmatter(p)
        desc = fm.get("description")
        if not desc:
            # Commands are plain markdown; use the first real line as the summary
            # rather than inventing one.
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        t = line.strip().lstrip("#").strip()
                        if t:
                            desc = t[:300]
                            break
            except OSError:
                desc = None
        rows.append(
            {
                "skill_key": f"command:{name}",
                "kind": "command",
                "name": name,
                "description": desc,
                "source_path": os.path.relpath(p, _REPO_ROOT),
                "department": None,
            }
        )

    # Capabilities are the dispatch surface — what delegate_task/dispatch accept.
    # Read from the live map, never from the prose copy in the rules files, which
    # is exactly the thing that drifts.
    try:
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        scopes["capability"] = True
        for cap, dept in sorted(CAPABILITY_DEPARTMENT_MAP.items()):
            rows.append(
                {
                    "skill_key": f"capability:{cap}",
                    "kind": "capability",
                    "name": cap,
                    "description": None,
                    "source_path": None,
                    "department": dept,
                }
            )
    except Exception as exc:  # noqa: BLE001 - a failed import is an uncollected scope
        scopes["capability"] = False
        logger.warning("platform_registry: CAPABILITY_DEPARTMENT_MAP unavailable (%s)", exc)

    collect_skills.scopes = scopes  # type: ignore[attr-defined]
    return rows


_SKILL_COLLECTED = ("kind", "name", "description", "source_path", "department")


def reconcile_skills(skills: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Upsert skills; mark vanished ones absent. Never deletes, never writes notes."""
    if skills is None:
        skills = collect_skills()
        scopes = getattr(collect_skills, "scopes", {})
    else:
        scopes = {k: True for k in ("skill", "command", "capability")}
    if not skills:
        raise ValueError("refusing to reconcile an empty skill set — that would mark every skill absent")

    now = now_utc()
    summary = {
        "collected": len(skills),
        "inserted": 0,
        "updated": 0,
        "absent": 0,
        "reappeared": 0,
        "scopes": scopes,
    }
    cols = ", ".join(_SKILL_COLLECTED)
    placeholders = ", ".join(["%s"] * len(_SKILL_COLLECTED))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _SKILL_COLLECTED)

    with get_db_cursor(commit=True) as (_conn, cur):
        before = _snapshot(cur, "skill")
        cur.execute("SELECT skill_key, status FROM platform_registry_skill")
        existing = {
            (r["skill_key"] if isinstance(r, dict) else r[0]): (r["status"] if isinstance(r, dict) else r[1])
            for r in cur.fetchall()
        }

        for s in skills:
            cur.execute(
                f"""
                INSERT INTO platform_registry_skill (skill_key, {cols}, status, first_seen_at, last_seen_at, collected_at)
                VALUES (%s, {placeholders}, 'present', %s, %s, %s)
                ON CONFLICT (skill_key) DO UPDATE SET
                    {updates},
                    status       = 'present',
                    last_seen_at = EXCLUDED.last_seen_at,
                    collected_at = EXCLUDED.collected_at
                """,
                [s["skill_key"], *[s[c] for c in _SKILL_COLLECTED], now, now, now],
            )
            prior = existing.get(s["skill_key"])
            if prior is None:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
                if prior == "absent":
                    summary["reappeared"] += 1

        seen = {s["skill_key"] for s in skills}
        # ONLY within a collected scope — a missing .claude/commands mount must
        # not erase 18 real commands from the registry.
        gone = [
            k
            for k, st in existing.items()
            if k not in seen and st != "absent" and scopes.get(k.split(":", 1)[0], False)
        ]
        if gone:
            cur.execute(
                "UPDATE platform_registry_skill SET status='absent', collected_at=%s WHERE skill_key = ANY(%s)",
                (now, gone),
            )
            summary["absent"] = len(gone)

        summary["changes"] = _emit_changes(cur, "skill", before, _snapshot(cur, "skill"))

    return summary


def get_skills(include_absent: bool = True) -> list[dict[str, Any]]:
    where = "" if include_absent else "WHERE status = 'present'"
    with get_db_cursor() as (_conn, cur):
        cur.execute(f"SELECT * FROM platform_registry_skill {where} ORDER BY kind, name")
        return [dict(r) for r in cur.fetchall()]


# ============================================================================
# PHASE 4 — the change feed (task #5230)
#
# A registry that only holds current state answers "what exists?" but never
# "what changed?" — and every incident this session began with a transition
# nobody observed: a DNS rewrite that swept in `mesh.`, a node control URL
# pointing at a dead tunnel for a month, three weeks of backups not reaching
# Drive. The state was observable in each case; the CHANGE was not.
#
# APPEND-ONLY. Rows are never updated or deleted — a feed you can rewrite is not
# evidence.
# ============================================================================

# Only fields worth waking someone for. `started_at` and `collected_at` change on
# every poll; recording them would bury the signal under its own exhaust.
_TRACKED_FIELDS = {
    "module": ("enabled", "route", "category", "blueprint_import", "minimum_role"),
    "service": ("container_state", "image", "drift_status"),
    "skill": ("description", "source_path", "department"),
}
_ENTITY_TABLE = {
    "module": ("platform_registry_module", "module_id"),
    "service": ("platform_registry_service", "service_key"),
    "skill": ("platform_registry_skill", "skill_key"),
}


def _snapshot(cur, entity_type: str) -> dict[str, dict[str, Any]]:
    """Current (key -> {status, tracked fields}) for change detection."""
    table, keycol = _ENTITY_TABLE[entity_type]
    fields = _TRACKED_FIELDS[entity_type]
    cur.execute(f"SELECT {keycol} AS k, status, {', '.join(fields)} FROM {table}")
    out: dict[str, dict[str, Any]] = {}
    for r in cur.fetchall():
        d = dict(r) if isinstance(r, dict) else dict(zip(["k", "status", *fields], r))
        out[d["k"]] = d
    return out


def _emit_changes(cur, entity_type: str, before: dict, after: dict) -> int:
    """Append one row per observed transition. Returns how many were written."""
    rows: list[tuple] = []
    for key, now_row in after.items():
        was = before.get(key)
        if was is None:
            rows.append((entity_type, key, "appeared", None, None, None))
            continue
        if was["status"] == "absent" and now_row["status"] == "present":
            rows.append((entity_type, key, "reappeared", None, None, None))
        elif was["status"] == "present" and now_row["status"] == "absent":
            rows.append((entity_type, key, "vanished", None, None, None))
        for f in _TRACKED_FIELDS[entity_type]:
            o, n = was.get(f), now_row.get(f)
            if o != n:
                rows.append(
                    (entity_type, key, "changed", f, None if o is None else str(o), None if n is None else str(n))
                )
    # A key present in `before` but missing from `after` cannot happen — nothing
    # is ever deleted — so its disappearance would be a BUG, not a platform event.
    for key in before:
        if key not in after:
            logger.error(
                "platform_registry: %s row %s DISAPPEARED from the table — rows must never be deleted", entity_type, key
            )

    if rows:
        cur.executemany(
            "INSERT INTO platform_registry_change (entity_type, entity_key, change_type, field, old_value, new_value) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def recent_changes(limit: int = 50, entity_type: str | None = None, since_hours: int | None = None) -> list[dict]:
    where, params = [], []
    if entity_type:
        where.append("entity_type = %s")
        params.append(entity_type)
    if since_hours:
        where.append("detected_at > now() - (%s || ' hours')::interval")
        params.append(str(since_hours))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            f"SELECT * FROM platform_registry_change {clause} ORDER BY detected_at DESC, id DESC LIMIT %s",
            [*params, limit],
        )
        return [dict(r) for r in cur.fetchall()]


# ============================================================================
# PHASE 4 — the scheduled collector + the disappearance alarm (task #5230)
# ============================================================================

WORK_CONTROL_KEY = "platform_registry"


def run_registry_collection(with_provenance: bool = False) -> dict[str, Any]:
    """Collect every registry scope, then alarm on anything that VANISHED.

    Gated by work_control_service so it can be turned off from the DHQ Autonomy
    tab without a deploy, like every other recurring job.

    EACH SCOPE IS INDEPENDENT. A failure in one must not abort the others — a
    broken docker socket should not also stop skills from being tracked. Every
    failure is reported in the result rather than raised, because this runs
    unattended and a job that dies silently is worse than one that reports a
    partial success honestly.

    WHAT IT ALARMS ON. Only 'vanished'. Appearances and field changes are the
    normal churn of a live platform; a DISAPPEARANCE is the event nobody
    notices and everybody needs — a module dropped from the registry, a
    container gone, a skill file deleted. This is the same rule as the backup
    freshness monitor: absence is the finding.
    """
    try:
        from services.work_control_service import is_enabled

        if not is_enabled(WORK_CONTROL_KEY, default=True):
            return {"skipped": "disabled via work_control"}
    except Exception as exc:  # noqa: BLE001 - never let the gate break the job
        logger.warning("platform_registry: work_control unavailable (%s) — proceeding", exc)

    result: dict[str, Any] = {"ok": True, "scopes": {}, "errors": {}}
    for name, fn in (
        ("modules", lambda: reconcile()),
        ("services", lambda: reconcile_services(with_provenance=with_provenance)),
        ("skills", lambda: reconcile_skills()),
    ):
        try:
            result["scopes"][name] = fn()
        except Exception as exc:  # noqa: BLE001 - one bad scope must not kill the rest
            result["ok"] = False
            result["errors"][name] = f"{type(exc).__name__}: {exc}"
            logger.exception("platform_registry: %s collection failed", name)

    vanished = [c for c in recent_changes(limit=200, since_hours=1) if c["change_type"] == "vanished"]
    result["vanished"] = len(vanished)
    if vanished:
        _alert_vanished(vanished)
    return result


def _alert_vanished(vanished: list[dict]) -> None:
    """Telegram advisory. Best-effort — an alert failure must never break collection."""
    try:
        from services.telegram_service import send_system

        lines = [f"• {v['entity_type']} `{v['entity_key']}`" for v in vanished[:12]]
        if len(vanished) > 12:
            lines.append(f"…and {len(vanished) - 12} more")
        send_system(
            # The count is in the TITLE because send_system dedups on (title, source):
            # a fixed title would mute every later disappearance after the first.
            title=f"Platform registry: {len(vanished)} entry(ies) vanished",
            message=(
                "These were present in a previous collection and are gone now.\n"
                + "\n".join(lines)
                + "\n\nRows are retained with status='absent' — nothing was deleted."
            ),
            source="platform_registry",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("platform_registry: could not send vanish alert (%s)", exc)


def documented_but_absent() -> list[dict[str, Any]]:
    """Everything the registry knows about that is no longer there.

    This is the phantom-table class made queryable: `backups` and `backup_locks`
    were documented for months while not existing, and the only reason anyone
    found out was an outage. A row here is that same situation, caught early.
    """
    out: list[dict[str, Any]] = []
    with get_db_cursor() as (_conn, cur):
        for entity, (table, keycol) in _ENTITY_TABLE.items():
            cur.execute(
                f"SELECT {keycol} AS k, last_seen_at, notes FROM {table} WHERE status='absent' ORDER BY last_seen_at DESC"
            )
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {"k": r[0], "last_seen_at": r[1], "notes": r[2]}
                out.append(
                    {
                        "entity_type": entity,
                        "entity_key": d["k"],
                        "last_seen_at": d["last_seen_at"],
                        "notes": d["notes"],
                    }
                )
    return out
