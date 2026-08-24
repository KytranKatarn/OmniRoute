"""Assemble a PROPOSED manifest of work for the owner to approve.

Never opens a window and never merges. It writes 'planned' windows only;
opening one is the owner's act in the cockpit.

Gathering is bounded PER SOURCE. #5002: the engine once ranked its first
in-scope issue at 744 against a fetch limit of 200, so every cycle no-opped
while looking healthy. A global cap across a 3,045-row pool repeats that.
"""

import json
import logging

from database import get_db_cursor
from services.lane_classifier import classify

log = logging.getLogger(__name__)

DEFAULT_PER_SOURCE_CAP = 25


def _fetch_tasks(limit: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, title, description FROM unified_tasks
                WHERE status = 'pending' ORDER BY priority DESC NULLS LAST, id LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _proposal_file_path(module_name, metadata) -> str | None:
    """Resolve a proposal's file_path: metadata['file_path'] wins, else synthesize
    from module_name, else None.

    Round 1 measured 2026-08-23: only 3/1361 approved proposals carry
    module_name, but metadata (jsonb, present on all rows) carries a
    populated file_path key on 812/1361 — module_name-only synthesis dropped
    99.8% of this source silently.

    Values are passed through UNTRANSLATED. Real ones look like
    'platform_v2/tools/consciousness/log_ingestor.py'; others are
    placeholders ('[AI_BRIDGE]/x.py') or cross-repo ('standalone_...',
    'website_...'). Those match no lane prefix and the classifier correctly
    drops them — normalizing a placeholder into a real path would be
    guessing an item INTO scope, which this design must never do.
    """
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = None
    meta_path = metadata.get("file_path") if isinstance(metadata, dict) else None
    if meta_path:
        return meta_path
    mod = (module_name or "").strip()
    return f"platform_v2/tools/{mod}/" if mod else None


def _fetch_proposals(limit: int) -> list:
    """⚠️ improvement_proposals has NO file_path column — verified 2026-08-23.

    It carries `module_name` (thin coverage) and `metadata` jsonb (the real
    signal — see `_proposal_file_path`). Selecting a `file_path` column here
    raises UndefinedColumn, which _safe() swallows, leaving this source
    permanently and silently empty — the same "unmonitored while appearing
    monitored" shape as the phantom `backups` table (#2366).
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, title, module_name, metadata FROM improvement_proposals
                WHERE status = 'approved' ORDER BY id DESC LIMIT %s""",
            (limit,),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["file_path"] = _proposal_file_path(d.get("module_name"), d.get("metadata"))
            rows.append(d)
        return rows


def _fetch_code_issues(limit: int, prefixes: tuple) -> list:
    """Delegates to the existing server-side scope filter (#5002) — it only ever
    NARROWS, and the caller supplies its own prefixes so there is one source of
    truth for scope.

    ⚠️ scan_service.get_issues returns {"success": ..., "issues": [...]}, never
    a bare list — round 1 returned the dict straight through, and
    gather_candidates' rows[:per_source_cap] slice (OUTSIDE _safe()) then
    raised TypeError on every run instead of degrading gracefully.

    MINOR (#380 review round 2): no scope means no rows, not every row.
    get_issues' own `if path_prefixes:` treats an EMPTY list exactly like None
    (both falsy) and fetches unfiltered — so `path_prefixes=list(prefixes) or
    None` used to explicitly convert "no scope given" into "no filter at all".
    Nothing in this branch currently calls with empty prefixes (lane_classifier
    still drops everything afterwards either way), but short-circuiting here
    is defence-in-depth rather than relying on that second layer.
    """
    if not prefixes:
        return []

    from services import scan_service

    result = scan_service.get_issues(status="open", limit=limit, auto_fixable=True, path_prefixes=list(prefixes))
    return result.get("issues", [])


def _safe(fn, *args) -> list:
    """One broken source must not take the whole proposer down. Fewer items, never an error."""
    try:
        return fn(*args) or []
    except Exception as exc:  # noqa: BLE001 - fail closed
        log.warning("proposer: source %s failed (%s) — skipping", getattr(fn, "__name__", fn), exc)
        return []


def gather_candidates(lane_prefixes: dict, per_source_cap: int = DEFAULT_PER_SOURCE_CAP) -> list:
    """Return type is unchanged (list) — Task 4 consumes this directly.

    A source can gather rows and keep NONE of them (e.g. unified_tasks: 339
    pending, 0 carry a usable file_path — every one drops for "no path"). That
    must be VISIBLE, not silent — the same "unmonitored while appearing
    monitored" shape as the phantom `backups` table (#2366). One INFO line per
    call reports gathered/kept/skipped per source; no per-item logging (noise
    at these volumes).

    The per-item work (classify() + candidate dict build) is individually
    guarded. _safe() only wraps the three FETCHERS — a single malformed row
    surviving a fetch and then breaking classify() is the identical failure
    class as round 1's dict-slice crash, just one loop iteration deeper.
    Fail-closed means SKIP the bad item, never abort the whole run.
    """
    all_prefixes = tuple(p for prefixes in lane_prefixes.values() for p in prefixes)
    sources = (
        ("unified_task", _safe(_fetch_tasks, per_source_cap)),
        ("proposal", _safe(_fetch_proposals, per_source_cap)),
        ("code_issue", _safe(_fetch_code_issues, per_source_cap, all_prefixes)),
    )

    out = []
    summary = []
    for source, rows in sources:
        gathered = rows[:per_source_cap]
        kept = 0
        skipped = 0
        for row in gathered:
            try:
                verdict = classify(row, lane_prefixes)
                if not verdict["lane"]:
                    continue
                kept += 1
                out.append(
                    {
                        "source": source,
                        "ref": str(row.get("id")),
                        "title": (row.get("title") or "")[:200],
                        "file_path": row.get("file_path"),
                        "lane": verdict["lane"],
                        "tier": verdict["tier"],
                        "reason": verdict["reason"],
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not abort the run
                skipped += 1
                log.warning("proposer: %s row %r unusable (%s) — skipping", source, row, exc)
        summary.append(f"{source} gathered={len(gathered)} kept={kept} skipped={skipped}")

    log.info("proposer: %s", " | ".join(summary))
    return out


DEFAULT_MAX_ITEMS = 15

# CRITICAL (#380 review round 2): the proposed window's start must sit
# comfortably beyond maintenance_window_driver's own announce lead
# (MAINTENANCE_ANNOUNCE_LEAD_MIN, dept_hq/jobs.py, default 60 min). That driver
# runs every 5 min and, in ONE tick, both announces a 'planned' window whose
# start has come within its lead time AND opens an 'announced' window whose
# start has arrived. Scheduling with scheduled_start=now_utc() (the original
# form) meant BOTH conditions were already true the instant the window was
# created — the driver would announce AND open it, unattended, before the
# owner ever saw the manifest. This lead is chosen well beyond the driver's
# default so the window is still merely 'planned' when a human looks at it.
PROPOSED_WINDOW_LEAD_MINUTES = 24 * 60  # 24h — a full day to review before it can even announce


def propose_manifest(lane_prefixes: dict, repo: str, max_items: int = DEFAULT_MAX_ITEMS, dry_run: bool = False) -> dict:
    """Draft a PLANNED window the owner can review, trim and approve.

    Never opens the window. add_item() refuses to extend a manifest once open,
    so the list must be right-sized BEFORE approval — hence the cap, and hence
    reporting what was dropped instead of truncating silently.
    """
    candidates = gather_candidates(lane_prefixes)
    chosen = candidates[:max_items]
    dropped = len(candidates) - len(chosen)
    items = [dict(c, repo=repo) for c in chosen]

    if dropped:
        log.info("proposer: proposing %d item(s), %d dropped by the cap", len(items), dropped)

    if not items:
        return {"ok": True, "window_id": None, "items": [], "dropped": dropped, "dry_run": dry_run}
    if dry_run:
        return {"ok": True, "window_id": None, "items": items, "dropped": dropped, "dry_run": True}

    from datetime import timedelta

    from services.maintenance_schedule_service import add_item, schedule_window
    from services.time_utils import now_utc

    win = schedule_window(
        now_utc() + timedelta(minutes=PROPOSED_WINDOW_LEAD_MINUTES),
        reason=f"Proposed by A.R.C.H.I.E. — {len(items)} item(s) for {repo}",
        created_by="proposer",
    )
    window_id = win["id"] if isinstance(win, dict) else win
    for it in items:
        add_item(
            window_id, title=it["title"], item_type=it["source"], ref=it["ref"], added_by="proposer", repo=it["repo"]
        )
    return {"ok": True, "window_id": window_id, "items": items, "dropped": dropped, "dry_run": False}
