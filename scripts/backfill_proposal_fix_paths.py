#!/usr/bin/env python3
"""Backfill metadata.fix_path on code-health proposals whose file_path is a token (#5945).

`file_path` is a FINGERPRINT KEY — `audit_pipeline._audit_file_path` deliberately keeps a
"["-prefixed module token so a re-audit matches the original proposals. Correct for
matching, useless for FIXING: nothing opens "[AI_BRIDGE]/semantic_search.py". 124 of the
327 still_open static proposals carried one, so no fixer could ever move them.

⚠️ This ADDS a sibling key. It never touches file_path. Rewriting file_path would break
fingerprint matching, drop every affected proposal out of the reverify's `current` set, and
flip them all to "fixed" — a real backlog turned into a fake clean bill of health.

Only writes when the resolved path EXISTS on disk, so a token whose root is unknown (or a
file that has since moved) yields no fix_path rather than one pointing at nothing.

DRY-RUN BY DEFAULT. --apply to write.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/app")

# The same repo seen from different places: the container mounts platform_v2 at /app and
# the repo root at /mnt/archie_brain; a host checkout has everything under one root.
_PREFIXES = ("/mnt/archie_brain", os.getcwd(), "")


def on_disk(rel: str) -> str | None:
    for pre in _PREFIXES:
        if pre and os.path.exists(os.path.join(pre, rel)):
            return os.path.join(pre, rel)
    # container: platform_v2/... is mounted at /app
    if rel.startswith("platform_v2/") and os.path.exists("/app/" + rel[len("platform_v2/") :]):
        return "/app/" + rel[len("platform_v2/") :]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import json

    from database import get_db_cursor
    from services.audit_pipeline import resolve_fix_path

    with get_db_cursor(commit=False) as (_c, cur):
        cur.execute(
            """SELECT id, metadata->>'file_path' AS fp
                 FROM improvement_proposals
                WHERE metadata->>'source' = 'code_health_audit'
                  AND metadata->>'file_path' LIKE '[%'
                  AND metadata->>'fix_path' IS NULL"""
        )
        rows = [dict(r) for r in cur.fetchall()]

    wrote = no_root = missing = 0
    unresolved: dict[str, int] = {}
    for r in rows:
        rel = resolve_fix_path(r["fp"])
        if not rel:
            no_root += 1
            tok = (r["fp"] or "").partition("/")[0]
            unresolved[tok] = unresolved.get(tok, 0) + 1
            continue
        if not on_disk(rel):
            missing += 1
            continue
        wrote += 1
        if args.apply:
            with get_db_cursor(commit=True) as (_c2, cur2):
                cur2.execute(
                    "UPDATE improvement_proposals "
                    "SET metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id = %s",
                    (json.dumps({"fix_path": rel, "fix_path_source": "backfill_5945"}), r["id"]),
                )

    print(f"candidates: {len(rows)}")
    print(f"  resolvable + on disk : {wrote}")
    print(f"  no known root        : {no_root}  {unresolved}")
    print(f"  resolved but MISSING : {missing}")
    print("DRY RUN — pass --apply to write." if not args.apply else "APPLIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
