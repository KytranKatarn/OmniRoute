"""Close the merged-but-not-running gap on every merge path, and say why when it cannot.

The hub bind-mounts ``/mnt/archie_brain``, so a GitHub merge deploys nothing until the
HOST fast-forwards that checkout and restarts the containers (``hub_deploy``, signed
host command, ``git merge --ff-only`` — it never rewrites history). Only F.O.R.G.E.'s
``deploy_via_merge`` used to queue it, so a merge through ``merge_pr`` directly, the
/merge-pr skill, a Telegram tap or ``gh pr merge`` left the gap open until someone
noticed. ``hub_deploy_provenance`` noticed, but only by alarming (#5375).

THREE RULES
-----------
1. **One request path.** Every trigger calls ``request_hub_deploy`` — the merge choke
   point and the 15-minute monitor. Not per-caller: per-caller is how the gap existed.
2. **Only ask when it can succeed.** ``decide`` refuses (and reports WHY) when the
   checkout is on a working branch, dirty, or unreadable. A deploy the host will
   reject is noise; the reason is the useful output.
3. **Never pile up.** A cooldown stops 15-minute ticks and back-to-back merges queuing a
   restart each. The host handler has its own drain guard for in-flight reviews.

Everything here is best-effort and NEVER raises: it runs after a successful merge and
inside a monitor, and must not turn either into a failure.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 20 * 60
COOLDOWN_KEY = "hub_deploy:last_requested_at"

#: Paths that cannot change what the hub's two containers run. A PR touching ONLY these
#: does not need a restart (WTF ships to Citadel, the websites to Hostinger).
NON_HUB_PREFIXES = (
    "what-the-fact/",
    "website/",
    "websites/",
    "docs/",
    ".claude/",
    "kytran-business-suite/",
    "kytran-creed/",
    "kytran-server-manager/",
    "standalone/",
)

ACTION_DEPLOY = "deploy"
ACTION_NOOP = "noop"
ACTION_BLOCKED = "blocked"


def touches_hub(paths) -> bool:
    """True unless EVERY changed path is provably outside the hub runtime.

    ``None``/empty means "could not read the file list" — unknown is treated as
    relevant, because skipping a deploy that was needed is the failure being fixed.
    """
    if not paths:
        return True
    return any(not str(p).startswith(NON_HUB_PREFIXES) for p in paths)


def decide(state_status: str, facts: dict | None = None) -> tuple[str, str]:
    """PURE. ``hub_deploy_state`` status in, ``(action, reason)`` out."""
    facts = facts or {}
    branch = facts.get("branch")
    if state_status == "in_sync":
        return ACTION_NOOP, "hub is on main and running it"
    if state_status in ("needs_pull", "needs_restart"):
        return ACTION_DEPLOY, (
            "origin/main is ahead of the running hub"
            if state_status == "needs_pull"
            else ("code is on disk but the containers have not reloaded it")
        )
    if state_status == "feature_branch":
        return ACTION_BLOCKED, (
            f"the live checkout is on '{branch}', not main — a fast-forward would not move main. "
            "Switch it back to main (work in a worktree), then it deploys itself."
        )
    if state_status == "dirty":
        return (
            ACTION_BLOCKED,
            "the live checkout has uncommitted changes in the mounted tree — not auto-deploying over them",
        )
    return ACTION_BLOCKED, "the live checkout could not be read, so whether it is behind is unknown"


def _cooldown_remaining(now: float | None = None) -> float:
    now = time.time() if now is None else now
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (COOLDOWN_KEY,))
            row = cur.fetchone()
        last = float((row["value"] if row else 0) or 0)
        return max(0.0, COOLDOWN_SECONDS - (now - last))
    except Exception as exc:  # noqa: BLE001 — a broken cooldown must not block a deploy forever
        logger.debug("[hub_deploy_sync] cooldown unreadable: %s", exc)
        return 0.0


def _stamp_cooldown(now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO platform_settings (key, value, value_type, description, updated_at) "
                "VALUES (%s, %s, 'string', 'Last hub_deploy request (epoch s) — throttle', NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (COOLDOWN_KEY, str(now)),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[hub_deploy_sync] cooldown not stamped: %s", exc)


def request_hub_deploy(
    source: str, *, state: dict | None = None, changed_paths=None, check_paths: bool = False
) -> dict:
    """Queue a host ``hub_deploy`` when one is needed and possible. NEVER raises.

    Returns ``{"action": deploy|noop|blocked, "queued": bool, "reason": str, ...}``.
    """
    try:
        if check_paths and not touches_hub(changed_paths):
            return {"action": ACTION_NOOP, "queued": False, "reason": "PR touches nothing the hub runs"}

        if state is None:
            from services.hub_deploy_state import hub_deploy_state

            state = hub_deploy_state()
        status = state.get("status")
        action, reason = decide(status, state)
        out = {
            "action": action,
            "queued": False,
            "reason": reason,
            "status": status,
            "branch": state.get("branch"),
            "behind_main": state.get("behind_main"),
        }
        if action != ACTION_DEPLOY:
            return out

        wait = _cooldown_remaining()
        if wait > 0:
            out["reason"] = f"a hub_deploy was requested {int((COOLDOWN_SECONDS - wait) // 60)} min ago — waiting"
            out["action"] = ACTION_NOOP
            return out

        from tools.system_operations.host_command_client import submit_host_command

        command_id = submit_host_command("hub_deploy", {}, submitted_by=source)
        _stamp_cooldown()
        out.update(queued=True, command_id=command_id)
        logger.info("[hub_deploy_sync] queued hub_deploy (%s) via %s — %s", command_id, source, reason)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hub_deploy_sync] request failed (%s): %s", source, exc)
        return {"action": ACTION_BLOCKED, "queued": False, "reason": f"could not request a deploy: {exc}"}


def attention_item(details: dict | None, since_hours: float | None = None) -> dict | None:
    """PURE. Latest monitor ``details`` in, ONE Attention Needed entry (or None) out.

    Replaces "Job 'hub_deploy_provenance' failed 10x in 24h". That number counted
    15-minute CHECKS that saw drift — it rose with every merge and fell when someone
    pulled, and said nothing about what to do. This states the situation once and
    names the action. "failed" is now reserved for the job actually crashing.
    """
    d = details or {}
    drift = d.get("drift")
    if not drift or drift == "in_sync":
        return None
    dep = d.get("deploy") or {}
    behind = d.get("behind_main")
    lag = f"{behind} commit{'s' if behind != 1 else ''} behind main" if behind else "not running the latest main"
    age = ""
    if since_hours is not None:
        age = f" for {since_hours:.0f}h" if since_hours >= 1 else " for under an hour"
    if dep.get("queued"):
        return {
            "level": "info",
            "text": f"Hub is {lag}{age} — deploy queued, applies on the next host tick",
            "link_tab": "dispatch",
            "category": "deploy",
        }
    if dep.get("action") == ACTION_NOOP:
        return {
            "level": "info",
            "text": f"Hub is {lag}{age} — deploy already requested, waiting",
            "link_tab": "dispatch",
            "category": "deploy",
        }
    why = dep.get("reason") or "deploy could not be requested"
    return {
        "level": "warning",
        "text": f"Hub is {lag}{age} — needs a human: {why}",
        "link_tab": "dispatch",
        "category": "deploy",
    }
