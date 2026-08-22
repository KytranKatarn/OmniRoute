#!/usr/bin/env python3
"""Backfill platform_registry_module.notes from the on-disk capability index (#5948).

THE PROBLEM. `.claude/rules/module-capability-index.md` says it is REGENERATED and that
curated context must be added via `platform_registry_service.set_notes()` — "never by
editing this file". Each module block renders as "**Notes** (curated, survives
regeneration): ...". But `set_notes()` has ZERO production callers: everyone edits the
FILE. `generate_registry_docs.py` renders notes FROM THE DB and does a whole-file
`write_text()`, so "survives regeneration" is only true for text that reached the DB.

The two have diverged. Measured 2026-08-22: the DB note for `department_hq` still opened
"12 tabs — Overview, Org Chart, Roster, Work Tracking, Performance ..." — the exact wrong
list PR #2741 corrected THAT DAY. Regenerating would have silently reverted it, and the
generator was actively printing "DRIFT: ... regenerate it".

THIS SCRIPT makes the DB authoritative, as the header already claims, by parsing each
rendered Notes block back out of the file and writing it to the column. After it runs, a
regeneration is safe and the header becomes true.

DRY-RUN BY DEFAULT. Pass --apply to write.

⚠️ Only modules whose file text DIFFERS from the DB are touched, and a module present in
the DB but absent from the file is left ALONE — never blanked. Losing a curated note to a
"cleanup" is the failure this whole task exists to prevent.
"""
from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, "/app")

INDEX = "/mnt/archie_brain/.claude/rules/module-capability-index.md"
_HEAD = re.compile(r"^###\s+.*?—\s+`([a-z0-9_]+)`\s*$", re.M)
_MARK = "- **Notes** (curated, survives regeneration): "


def parse(text: str) -> dict[str, str]:
    """module_id -> the note body rendered under it."""
    out: dict[str, str] = {}
    heads = list(_HEAD.finditer(text))
    for i, m in enumerate(heads):
        block = text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        idx = block.find(_MARK)
        if idx < 0:
            continue
        body = block[idx + len(_MARK) :]
        # the note runs to the next section/heading/rule at line start
        cut = re.search(r"^(?:##\s|###\s|---\s*$|\*Phase \d)", body, re.M)
        out[m.group(1)] = (body[: cut.start()] if cut else body).rstrip()
    return out


def _norm(v: str) -> str:
    """Strip a trailing horizontal rule before comparing.

    Several DB notes end with a stray "\n\n---" — a section separator that was captured
    into the note at some earlier point. The generator does not render it, so the file copy
    correctly lacks it. Without this, those modules look 5 chars "richer" in the DB and trip
    the divergence guard, hiding the ONE genuine conflict in seven false ones.
    """
    return re.sub(r"\s*-{3,}\s*$", "", (v or "").strip()).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is dry-run)")
    args = ap.parse_args()

    from database import get_db_cursor
    from services import platform_registry_service as prs

    parsed = parse(open(INDEX, encoding="utf-8").read())
    with get_db_cursor(commit=False) as (_c, cur):
        cur.execute("SELECT module_id, COALESCE(notes, '') AS notes FROM platform_registry_module")
        current = {r["module_id"]: r["notes"] for r in cur.fetchall()}

    same = changed = added = 0
    manual: list[str] = []
    for mid, note in sorted(parsed.items()):
        if mid not in current:
            print(f"  SKIP (not in registry): {mid}")
            continue
        was = current[mid]
        if _norm(was) == _norm(note):
            same += 1
            continue
        # ⚠️ TWO-WAY DIVERGENCE GUARD. This is not a one-way sync: for at least one module
        # the DB is the CORRECTED copy and the file is stale-and-wrong. Measured 2026-08-22,
        # kytran_system_ops — file: "gitignored, no separate git repo"; DB: "gitignored BY
        # THE PLATFORM REPO (.gitignore:156), but it IS its own git repo with remote
        # KytranKatarn/kytran-system-operations". The DB is right (see .claude/rules/
        # multi-repo.md). Overwriting it would destroy a correction and reinstate a false
        # statement. A bulk sync over N modules is N decisions -- find the odd one out first.
        if len(_norm(was)) > len(_norm(note)):
            manual.append(mid)
            print(f"  MANUAL {mid:<26} db={len(_norm(was)):>6} > file={len(_norm(note)):>6} — DB is RICHER, skipping")
            continue
        if _norm(was):
            changed += 1
        else:
            added += 1
        print(f"  {'UPDATE' if _norm(was) else 'ADD   '} {mid:<26} db={len(was):>6}  file={len(note):>6}")
        if args.apply:
            prs.set_notes(mid, note)

    only_db = sorted(m for m, n in current.items() if n.strip() and m not in parsed)
    print(
        f"\nparsed from file: {len(parsed)}   unchanged: {same}   updated: {changed}   added: {added}   manual: {len(manual)}"
    )
    if manual:
        print("NEEDS A HUMAN (DB richer than file — sync the FILE from the DB instead): " + ", ".join(manual))
    if only_db:
        print(f"LEFT ALONE (in DB, no Notes block in file): {', '.join(only_db)}")
    print("DRY RUN — pass --apply to write." if not args.apply else "APPLIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
