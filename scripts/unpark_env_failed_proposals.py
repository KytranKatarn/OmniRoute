#!/usr/bin/env python3
"""Un-park audit proposals that were parked by an ENVIRONMENT failure, not a verdict.

Background (2026-07-20): `dispatch_proposal_fix` imported the DHQ dispatcher with no
sys.path guard, so any process that had not run the app boot path raised
ModuleNotFoundError('db') instantly. `dispatch_audit_proposals` classified that as a
PERMANENT failure and called `_mark_dispatch_attempted()`. Because the drain query
filters on `(metadata->>'dispatch_attempted') IS NULL`, those proposals became
invisible to the drain forever.

18 unrelated proposals were parked in 0.8 seconds (14:52:46.58 -> 14:52:47.40) across
security_network, game_studio, faith, email_manager, backup_manager and ai_bridge --
nothing about the proposals was wrong. This clears that park so they re-enter the drain.

Deliberately NARROW: only rows whose dispatch_error matches a known environment
signature are touched. `find_not_located`, `unparseable`, C.R.E.E.D. denials and every
other genuine verdict are left exactly as they are.

Reversible: the original park is preserved under metadata.unparked_from, so a row can
be restored without guessing what it used to say.

Usage:
    python3 scripts/unpark_env_failed_proposals.py            # dry run (default)
    python3 scripts/unpark_env_failed_proposals.py --apply    # perform the update
"""

import argparse
import sys

sys.path.insert(0, "/app")

from database import get_db_cursor  # noqa: E402

# Only these. An environment failure says nothing about the proposal.
ENV_ERROR_PATTERNS = (
    "%No module named%",
    "%ModuleNotFoundError%",
    "%ImportError%",
)

SELECT_SQL = """
    SELECT id,
           COALESCE(metadata->>'issue_code', '?')   AS issue_code,
           COALESCE(metadata->>'module_name', '?')  AS module_name,
           COALESCE(metadata->>'dispatch_error','') AS dispatch_error,
           status
    FROM improvement_proposals
    WHERE metadata->>'source' = 'code_health_audit'
      AND metadata ? 'dispatch_attempted'
      AND status IN ('pending', 'approved', 'fix_requested')
      AND (%s)
    ORDER BY id
"""

# Drop the park keys so the drain sees the row again; keep a restore point.
UPDATE_SQL = """
    UPDATE improvement_proposals
    SET metadata = (metadata
                    - 'dispatch_attempted'
                    - 'dispatch_attempted_at'
                    - 'dispatch_error'
                    - 'defer_count'
                    - 'last_defer_error')
                   || jsonb_build_object(
                        'unparked_at',   now()::text,
                        'unparked_by',   'unpark_env_failed_proposals',
                        'unparked_from', metadata->'dispatch_error')
    WHERE id = ANY(%s)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="perform the update (default: dry run)")
    args = ap.parse_args()

    where = " OR ".join(["metadata->>'dispatch_error' ILIKE %s"] * len(ENV_ERROR_PATTERNS))

    with get_db_cursor(commit=args.apply) as (conn, cur):
        cur.execute(SELECT_SQL % where, ENV_ERROR_PATTERNS)
        rows = cur.fetchall()

        if not rows:
            print("No environment-parked proposals found — nothing to do.")
            return 0

        print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(rows)} environment-parked proposal(s)\n")
        for r in rows:
            print(f"  #{r['id']:<6} {r['status']:<14} {r['issue_code']:<22} {r['module_name'][:34]}")
        print(f"\n  parked by: {rows[0]['dispatch_error'][:90]}")

        if not args.apply:
            print("\nDry run — nothing changed. Re-run with --apply to un-park.")
            return 0

        cur.execute(UPDATE_SQL, ([r["id"] for r in rows],))
        print(f"\nUn-parked {cur.rowcount} proposal(s). They re-enter the next drain cycle.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
