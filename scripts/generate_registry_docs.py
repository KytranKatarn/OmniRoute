#!/usr/bin/env python3
"""Render the module capability index FROM the registry (task #5230, Phase 1).

    docker exec archie_platform python3 /mnt/archie_brain/scripts/generate_registry_docs.py
    ... --check      exit 1 if the file on disk differs from what we would render
    ... --stdout     print instead of writing

WHY A GENERATOR AND NOT A BETTER HABIT
The old index was 314 hand-typed lines read FIRST by every new session, and it
asserted things that were not true — two phantom tables (`backups`,
`backup_locks`) that left backups unmonitored while APPEARING monitored, and
three modules listed as writable by an automated agent that never were. Those
survived because a human wrote them once and nobody re-derived them. "Be more
careful" has already been tried; this makes carefulness unnecessary.

TWO PROPERTIES THE OUTPUT MUST HAVE
1. A GENERATED header, so nobody hand-edits it and loses the edit on the next run.
2. A generated_at stamp and a source-of-truth line, so the document DECLARES ITS
   OWN STALENESS. A doc that cannot be stale is impossible; a doc that hides how
   stale it is, is the actual defect.

Human rationale lives in `platform_registry_module.notes` and is rendered back
in, so regeneration never destroys the genuinely valuable half.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services.platform_registry_service import (  # noqa: E402
    get_modules,
    reconcile,
    registry_summary,
)
from services.time_utils import format_local  # noqa: E402

OUT = Path("/mnt/archie_brain/.claude/rules/module-capability-index.md")

_CATEGORY_TITLES = {
    "admin_operations": "Admin Operations",
    "ai_command": "AI Command",
    "saas_services": "SaaS Services",
    "project_knowledge": "Project & Knowledge",
    "applications_concepts": "Applications & Concepts",
    "creative_studios": "Creative Studios",
    "crypto": "Crypto",
    "media_outreach": "Media & Outreach (standalones)",
    "coming_soon": "Coming Soon",
}


def _status_badge(m: dict) -> str:
    if m["status"] == "absent":
        return "🚨 ABSENT"
    if m["coming_soon"]:
        return "⏳ coming_soon"
    if not m["enabled"]:
        return "⛔ disabled"
    if m["beta"]:
        return "🅱 beta"
    return "✅ enabled"


def render() -> str:
    mods = get_modules(include_absent=True)
    s = registry_summary()
    stamp = format_local(s["collected_at"]) if s.get("collected_at") else "never"

    L: list[str] = []
    L.append("<!-- GENERATED FILE — DO NOT EDIT BY HAND.")
    L.append("     Regenerate:  docker exec archie_platform python3 \\")
    L.append("                    /mnt/archie_brain/scripts/generate_registry_docs.py")
    L.append("     Source of truth: platform_v2/module_registry.py -> platform_registry_module table.")
    L.append("     Hand-written rationale belongs in the `notes` column, NOT in this file —")
    L.append("     anything typed here is lost on the next run. Task #5230. -->")
    L.append("")
    L.append("# Master Module Capability Index")
    L.append("")
    L.append(f"**Generated**: {stamp} · **Source**: `module_registry.MODULES` (live import, not prose)")
    L.append("")
    L.append(
        f"**{s['present']} modules registered** — {s['enabled']} enabled, "
        f"{s['present'] - s['enabled']} disabled/coming-soon, {s['absent']} absent. "
        f"{s['with_notes']} carry curated notes."
    )
    L.append("")
    L.append(
        "> This file is REGENERATED. If it disagrees with the platform, the platform is "
        "right and this file is stale — check the Generated stamp above before trusting it. "
        "It exists because the hand-maintained predecessor documented two tables that do not "
        "exist (`backups`, `backup_locks`), which left backups unmonitored while appearing "
        "monitored, and listed three modules as writable by an automated agent that never were."
    )
    L.append("")

    absent = [m for m in mods if m["status"] == "absent"]
    if absent:
        L.append("## 🚨 Absent — collected before, not present in the latest run")
        L.append("")
        L.append("A module that vanished is the most interesting thing this index can tell you.")
        L.append("Rows are never deleted, so the disappearance stays visible.")
        L.append("")
        L.append("| Module | Last seen |")
        L.append("|--------|-----------|")
        for m in absent:
            L.append(f"| `{m['module_id']}` | {format_local(m['last_seen_at'])} |")
        L.append("")

    L.append("## Legend")
    L.append("")
    L.append("✅ enabled · 🅱 beta · ⏳ coming_soon · ⛔ disabled · 🚨 absent")
    L.append("")

    by_cat: dict[str, list[dict]] = {}
    for m in mods:
        if m["status"] == "absent":
            continue
        by_cat.setdefault(m["category"], []).append(m)

    for cat in sorted(by_cat, key=lambda c: (list(_CATEGORY_TITLES).index(c) if c in _CATEGORY_TITLES else 99, c)):
        rows = by_cat[cat]
        L.append(f"## {_CATEGORY_TITLES.get(cat, cat)} ({len(rows)})")
        L.append("")
        for m in rows:
            route = m["route"] or m["external_url"] or "—"
            L.append(f"### {m['name']} — `{m['module_id']}`")
            L.append("")
            L.append(f"- **Status**: {_status_badge(m)} · **Route**: `{route}` · **Version**: {m['version'] or '—'}")
            if m["description"]:
                L.append(f"- **Description**: {m['description']}")
            perms = m["required_permissions"] or []
            L.append(
                f"- **Access**: role `{m['minimum_role'] or '—'}` · tier `{m['minimum_tier'] or '—'}`"
                + (f" · perms {', '.join(f'`{p}`' for p in perms)}" if perms else " · no explicit perms")
            )
            if m["blueprint_import"]:
                L.append(f"- **Blueprint**: `{m['blueprint_import']}`")
            elif m["external_url"]:
                L.append(f"- **Standalone** (launch tile only — no in-platform blueprint): {m['external_url']}")
            if m["tags"]:
                L.append(f"- **Tags**: {', '.join(m['tags'])}")
            if m.get("notes"):
                L.append(f"- **Notes** (curated, survives regeneration): {m['notes']}")
            L.append("")

    L.append("---")
    L.append("")
    L.append(
        "*Phase 1 of the Living Platform Registry (#5230): modules only. Services, skills, "
        "and the change feed follow in phases 2–4. Add curated context with "
        "`platform_registry_service.set_notes(module_id, text)` — never by editing this file.*"
    )
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if on-disk differs (no write)")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--no-collect", action="store_true", help="render from the table without re-collecting")
    a = ap.parse_args()

    if not a.no_collect:
        summary = reconcile()
        print(
            f"[registry] collected={summary['collected']} inserted={summary['inserted']} "
            f"updated={summary['updated']} absent={summary['absent']} reappeared={summary['reappeared']}",
            file=sys.stderr,
        )

    text = render()

    if a.stdout:
        print(text)
        return 0

    if a.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current == text:
            print("[registry] index is current")
            return 0
        print(f"[registry] DRIFT: {OUT} is out of date — regenerate it", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"[registry] wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
