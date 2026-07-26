#!/usr/bin/env python3
"""One-shot: lift curated prose out of the OLD hand-written capability index
into platform_registry_module.notes (task #5230, Phase 1).

WHY THIS SCRIPT EXISTS
The generator renders the index from live data. Run it against an empty `notes`
column and it produces a technically-accurate document that has LOST the
genuinely valuable half — the hand-won gotchas that cannot be derived from
`module_registry.py`:

    "SABnzbd set_config is unreliable — edit sabnzbd.ini directly (KB #261306)"
    "backups and backup_locks do NOT exist — locking is a FILE"
    "NEVER pass WTF_TECH_URL to browser JS"

Nobody can regenerate those from a dataclass. They are the accumulated cost of
real outages. Migrating them into a column the collector never touches is the
precondition for the generator being an improvement rather than a deletion.

Idempotent: only fills notes that are currently empty, so re-running never
clobbers a note someone has since curated by hand.

    python3 scripts/migrate_index_notes.py <old_index.md> [--dry-run]
"""

from __future__ import annotations

import re
import sys

sys.path.insert(0, "/app")

from services.platform_registry_service import get_modules  # noqa: E402
from database import get_db_cursor  # noqa: E402

# "### Backup Manager — `backup_manager` · `/tools/backup-manager` · ✅ · 🟢"
_HEAD = re.compile(r"^###\s+.*?`([a-z0-9_]+)`", re.M)


def parse_blocks(text: str) -> dict[str, str]:
    """Split the old index into per-module bodies keyed by module_id."""
    blocks: dict[str, str] = {}
    marks = list(_HEAD.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end]
        # Drop the remainder of the header line; keep the bullet prose.
        body = body.split("\n", 1)[1] if "\n" in body else ""
        # Stop at a category heading that follows the last module block.
        body = re.split(r"^##\s+", body, maxsplit=1, flags=re.M)[0]
        body = body.strip()
        if body:
            blocks[m.group(1)] = body
    return blocks


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dry = "--dry-run" in sys.argv
    text = open(sys.argv[1]).read()
    blocks = parse_blocks(text)

    known = {m["module_id"] for m in get_modules()}
    matched = {k: v for k, v in blocks.items() if k in known}
    orphans = sorted(set(blocks) - known)

    print(f"parsed {len(blocks)} blocks · {len(matched)} match a registered module · {len(orphans)} orphan")
    if orphans:
        # An orphan is a module documented in prose that the live registry does
        # not have — precisely the "documented but absent" class this whole task
        # is about. Report it; never silently drop it.
        print(f"  ORPHANS (documented but NOT in module_registry.py): {', '.join(orphans)}")

    if dry:
        for k in sorted(matched):
            print(f"  would set notes[{k}] = {len(matched[k])} chars")
        return 0

    filled = 0
    with get_db_cursor(commit=True) as (_conn, cur):
        for mid, body in matched.items():
            cur.execute(
                "UPDATE platform_registry_module SET notes = %s "
                "WHERE module_id = %s AND (notes IS NULL OR notes = '')",
                (body, mid),
            )
            filled += cur.rowcount
    print(f"filled {filled} notes (idempotent — already-curated notes left alone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
