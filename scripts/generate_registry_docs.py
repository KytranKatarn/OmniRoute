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
    get_services,
    reconcile,
    reconcile_services,
    registry_summary,
)
from services.time_utils import format_local  # noqa: E402

OUT = Path("/mnt/archie_brain/.claude/rules/module-capability-index.md")
OUT_SERVICES = Path("/mnt/archie_brain/.claude/rules/service-registry.md")

# Order here IS the section order of the generated doc (see the sort at the bottom of
# render_modules), so it is kept in step with dashboard_generator.get_categories_info()
# priorities — the doc then reads in the same order as the dashboard itself.
#
# ⚠️ A category missing from this map renders its RAW SLUG as a heading. Three were
# doing exactly that before 2026-09-11: `what_the_fact`, `placeholders_future` (whose
# key here was the never-used `coming_soon`), and — briefly — the new ones. Nothing
# joined this map to the ModuleCategory enum; tests/test_dashboard_categories.py now
# does, so a new category cannot ship as a slug again.
_CATEGORY_TITLES = {
    "admin_operations": "Admin Operations",
    "ai_command": "AI Command",
    "what_the_fact": "What The Fact",
    "creed": "C.R.E.E.D.",
    "saas_services": "SaaS Services",
    "project_knowledge": "Project & Knowledge",
    "applications_concepts": "Applications & Concepts",
    "crypto": "Crypto",
    "watch_series": "The Watch Series",
    "creative_studios": "Creative Studios",
    "placeholders_future": "Coming Soon",
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

    # Instruction-budget visibility (2026-09-25). This index is auto-loaded into every
    # Claude Code session's context alongside CLAUDE.md + every .claude/rules/*.md file;
    # together they were measured at 443,893 chars against Claude Code's ~150k budget,
    # and curated notes on just 3 modules (department_hq, repair_bay, backup_manager)
    # accounted for ~60% of every char this file has ever cost. Deliberately NOT
    # auto-truncated here: these notes are the only place a lot of hard-won incident
    # detail lives (no KB duplicate to fall back on the way learned-skills.md had), so a
    # blind character cut risks silently dropping the newest, most load-bearing
    # correction in a note that reads chronologically. This table exists so the
    # concentration is visible and actionable (move closed incidents into KB
    # `mistake_learned`/`vault_note` entries, keep only current-state facts here)
    # instead of invisible and merely large.
    _NOTE_FLAG_CHARS = 4000
    oversized = sorted(
        ((m["module_id"], len(m["notes"])) for m in mods if m.get("notes") and len(m["notes"]) > _NOTE_FLAG_CHARS),
        key=lambda x: -x[1],
    )
    if oversized:
        L.append(f"### ⚠️ Oversized curated notes (>{_NOTE_FLAG_CHARS} chars — compress, don't just read)")
        L.append("")
        L.append(
            "Candidates for moving closed/historical incident narrative into KB "
            "`mistake_learned`/`vault_note` entries, keeping only current-state facts here. "
            "Edit via `platform_registry_service.set_notes(module_id, text)`, never this file."
        )
        L.append("")
        L.append("| Module | Notes size |")
        L.append("|--------|-----------|")
        for mid, size in oversized:
            L.append(f"| `{mid}` | {size:,} chars |")
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


def render_services() -> str:
    """Render the SERVICES half (phase 2).

    Separate file from the module index because they answer different questions
    and refresh on different cadences — a container restarts hourly, a module
    changes on merge. Folding them together would make the whole document look
    stale every time a container blinked.
    """
    rows = get_services(include_absent=True)
    present = [r for r in rows if r["status"] == "present"]
    absent = [r for r in rows if r["status"] == "absent"]
    containers = [r for r in present if r["kind"] == "container"]
    products = [r for r in present if r["kind"] == "product"]
    running = [r for r in containers if r["container_state"] == "running"]
    stamp = max((r["collected_at"] for r in rows), default=None)
    prov_at = max((r["provenance_at"] for r in products if r["provenance_at"]), default=None)

    L = []
    L.append("<!-- GENERATED FILE — DO NOT EDIT BY HAND.")
    L.append("     Regenerate:  docker exec archie_platform python3 \\")
    L.append("                    /mnt/archie_brain/scripts/generate_registry_docs.py --services")
    L.append("     Sources: the docker daemon + scripts/deploy_drift_check.py check_products().")
    L.append("     Curated context belongs in the `notes` column. Task #5230 phase 2. -->")
    L.append("")
    L.append("# Service Registry")
    L.append("")
    L.append(
        f"**Collected**: {format_local(stamp) if stamp else 'never'} · "
        f"**Provenance measured**: {format_local(prov_at) if prov_at else 'never'}"
    )
    L.append("")
    L.append(
        f"{len(running)}/{len(containers)} hub containers running · "
        f"{len(products)} image-baked products · {len(absent)} absent."
    )
    L.append("")
    L.append("> Regenerated from live sources. **`fail_open` is an UNKNOWN, not a fault** —")
    L.append("> the product is unreachable or has no resolvable expected SHA. Do not read it")
    L.append("> as drift. Provenance and collection are timestamped separately because a cheap")
    L.append("> container-only run does not re-measure drift.")
    L.append("")

    if absent:
        L.append("## 🚨 Absent — seen before, not in the latest collection")
        L.append("")
        L.append("| Service | Kind | Last seen |")
        L.append("|---------|------|-----------|")
        for r in absent:
            L.append(f"| `{r['service_key']}` | {r['kind']} | {format_local(r['last_seen_at'])} |")
        L.append("")

    L.append("## Image-baked products — deploy provenance")
    L.append("")
    L.append("| Product | Drift | Baked | Expected | Endpoint |")
    L.append("|---------|-------|-------|----------|----------|")
    _badge = {"in_sync": "✅ in_sync", "drift": "🔴 DRIFT", "fail_open": "⚪ fail_open"}
    for r in sorted(products, key=lambda x: x["service_key"]):
        L.append(
            f"| `{r['service_key']}` | {_badge.get(r['drift_status'], '— not measured')} | "
            f"`{(r['baked_sha'] or '-')[:9]}` | `{(r['expected_sha'] or '-')[:9]}` | {r['version_url'] or '—'} |"
        )
    L.append("")

    L.append("## Hub containers")
    L.append("")
    L.append("| Container | State | Compose project | Ports | Image |")
    L.append("|-----------|-------|-----------------|-------|-------|")
    for r in sorted(containers, key=lambda x: (x["compose_project"] or "~", x["service_key"])):
        mark = "" if r["container_state"] == "running" else " ⚠"
        ports = ", ".join(r["ports"] or []) or "—"
        L.append(
            f"| `{r['service_key']}`{mark} | {r['container_state']} | {r['compose_project'] or '(bare docker run)'} "
            f"| {ports} | `{(r['image'] or '-')[:44]}` |"
        )
    L.append("")
    for r in rows:
        if r.get("notes"):
            L.append(f"- **`{r['service_key']}`** — {r['notes']}")
    L.append("")
    L.append("---")
    L.append("")
    L.append(
        "*Phase 2 of the Living Platform Registry (#5230). Add curated context with "
        "`platform_registry_service.set_service_notes(key, text)` — never by editing this file.*"
    )
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if on-disk differs (no write)")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--no-collect", action="store_true", help="render from the table without re-collecting")
    ap.add_argument("--services", action="store_true", help="render the SERVICE registry instead of modules")
    ap.add_argument("--provenance", action="store_true", help="with --services: re-measure deploy drift (slow)")
    a = ap.parse_args()

    if a.services:
        if not a.no_collect:
            s2 = reconcile_services(with_provenance=a.provenance)
            print(
                f"[registry] services collected={s2['collected']} inserted={s2['inserted']} "
                f"updated={s2['updated']} absent={s2['absent']} scopes={s2['scopes']}",
                file=sys.stderr,
            )
        text = render_services()
        if a.stdout:
            print(text)
            return 0
        if a.check:
            cur = OUT_SERVICES.read_text() if OUT_SERVICES.exists() else ""
            if cur == text:
                print("[registry] service registry is current")
                return 0
            print(f"[registry] DRIFT: {OUT_SERVICES} is out of date", file=sys.stderr)
            return 1
        OUT_SERVICES.parent.mkdir(parents=True, exist_ok=True)
        OUT_SERVICES.write_text(text)
        print(f"[registry] wrote {OUT_SERVICES} ({len(text.splitlines())} lines)")
        return 0

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
