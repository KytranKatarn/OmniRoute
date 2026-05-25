# Module-Aware Boot System — Design
**Dev HQ Task #3185 | Status: Design Complete | Date: 2026-05-25**

## Problem

The current `/archie-boot` protocol runs 4–7 MCP calls and loads ~20k context tokens on EVERY session start, regardless of what the session is actually working on. This burns expensive Opus context on irrelevant module data. Sessions working on, say, Gov Watch load full platform status + all 36 module details + agent roster when they only need Gov Watch, VPS deployment rules, and tier sync facts.

The `/archie-focus <module>` skill exists as a partial workaround but is not codified into the boot system itself.

## Solution

A **segmented boot** system: boot loads ONLY the context segments relevant to the declared session scope, using a segment registry with lazy loading. Full boot remains available via `/archie-boot`; focused boots via `/archie-focus <target>` load 3–5 segments instead of all 15+.

---

## Segment Registry

Each segment is a named block of boot context with a load cost estimate.

| Segment | Cost (tokens) | Contents | Triggers |
|---------|--------------|---------|---------|
| `core_identity` | ~1k | Owner identity, canonical login, service accounts, active fire from handoff | Always loaded |
| `platform_status` | ~2k | Agent counts, KB stats, active projects, recent decisions | Full boot only |
| `active_mistakes` | ~3k | Last 10 `mistake_learned` entries from KB | Full boot + any coding |
| `session_mode` | ~0.5k | Role (Architect/Executor), sibling session, pending specs | Always loaded |
| `agent_roster` | ~2k | 34 AI agents, departments, shift states | Fleet/dispatch work |
| `fleet_status` | ~2k | Node status, Headscale mesh IPs, resource budgets | Infra/deploy work |
| `dispatch_patterns` | ~1.5k | Dispatcher import paths, CAPABILITY_DEPARTMENT_MAP quick ref, ADR-002 | Any dispatch work |
| `module_govwatch` | ~2k | VPS path, Bridge URL, tier sync, APScheduler jobs, DB user, WIP files | gov-watch target |
| `module_wtf` | ~1.5k | 3-container arch, XSS rule, WTF_TECH_URL proxy rule, VPS path | wtf target |
| `module_kbs` | ~1k | Port 8091, 25 plugins, Stripe integration, standalone rules | kbs target |
| `module_consciousness` | ~2k | KB taxonomy, search patterns, embedding loop status, 62 mistakes | consciousness target |
| `module_dhq` | ~2k | 12 tabs, fleet routes, dispatch panel, S.I.G.N.A.L. tab | department-hq target |
| `module_media_studio` | ~2k | ADR-005 routing, ComfyUI fleet, contractor providers, portrait pipeline | media-studio target |
| `module_repair_bay` | ~1.5k | 8 tabs, PR review pipeline, F.O.R.G.E. analysis, Hostinger deploy path | repair-bay target |
| `module_email_manager` | ~1.5k | Stalwart rule, imap_uid gotcha, R.E.S.O.L.V.E. overlay, 49 mailboxes | email-manager target |
| `billing_infra` | ~2k | Stripe services, subscription_service, webhook pipeline, OAuth entitlements | billing/pricing work |
| `vps_deploy` | ~1k | rsync pattern, docker compose up --build, product dir map, mesh IPs | any VPS deploy |

---

## Target → Segment Mapping

```python
BOOT_TARGETS = {
    # Standalones
    "gov_watch":        ["core_identity", "session_mode", "active_mistakes", "module_govwatch", "vps_deploy"],
    "wtf":              ["core_identity", "session_mode", "active_mistakes", "module_wtf", "vps_deploy"],
    "kbs":              ["core_identity", "session_mode", "active_mistakes", "module_kbs"],
    "kso":              ["core_identity", "session_mode", "active_mistakes", "vps_deploy"],
    "civic_watch":      ["core_identity", "session_mode", "active_mistakes", "vps_deploy"],
    "legal_watch":      ["core_identity", "session_mode", "active_mistakes", "vps_deploy"],
    "market_watch":     ["core_identity", "session_mode", "active_mistakes", "vps_deploy"],
    # Platform modules
    "consciousness":    ["core_identity", "session_mode", "active_mistakes", "module_consciousness"],
    "department_hq":    ["core_identity", "session_mode", "active_mistakes", "module_dhq", "dispatch_patterns", "agent_roster"],
    "media_studio":     ["core_identity", "session_mode", "active_mistakes", "module_media_studio", "fleet_status"],
    "repair_bay":       ["core_identity", "session_mode", "active_mistakes", "module_repair_bay"],
    "email_manager":    ["core_identity", "session_mode", "active_mistakes", "module_email_manager"],
    # Cross-cutting concerns
    "fleet":            ["core_identity", "session_mode", "active_mistakes", "fleet_status", "agent_roster", "dispatch_patterns"],
    "dispatch":         ["core_identity", "session_mode", "active_mistakes", "dispatch_patterns", "agent_roster"],
    "billing":          ["core_identity", "session_mode", "active_mistakes", "billing_infra"],
    # Catchall
    "full":             "ALL",  # original /archie-boot behaviour
}
```

---

## Implementation

### Skill: `/archie-focus <target>`

The existing `/archie-focus` skill becomes the official focused boot entry point. Refactor to:

1. Parse `target` arg (e.g., `gov_watch`, `wtf`, `repair_bay`)
2. Look up segment list from `BOOT_TARGETS`
3. Load each segment via the appropriate MCP call or file read
4. Present a compact boot summary (target-scoped, not full platform)
5. Mark identity gate cleared (same as `/archie-boot`)

**Segment loading strategy:**
- `core_identity` → Read `feedback_owner-context.md` + top of `project_session-handoff.md`
- `active_mistakes` → `mcp__archie__search_knowledge(types=["mistake_learned"], limit=5)` scoped to target
- `module_*` → Read the corresponding `.claude/rules/<module>.md` file
- `platform_status` → `mcp__archie__get_quick_summary()`
- `agent_roster` → `mcp__archie__list_agents()`
- `fleet_status` → `mcp__archie__get_node_status()`
- `billing_infra` → Read relevant sections of unified pricing plan doc
- `vps_deploy` → Read `reference_vps-deploy-pattern.md`

### Token Savings Estimate

| Session type | Full boot | Focused boot | Savings |
|---|---|---|---|
| Gov Watch session | ~22k tokens | ~8k tokens | ~64% |
| WTF session | ~22k tokens | ~7k tokens | ~68% |
| Media Studio session | ~22k tokens | ~10k tokens | ~55% |
| Repair Bay session | ~22k tokens | ~8k tokens | ~64% |
| Full platform session | ~22k tokens | ~22k tokens | 0% (by design) |

### MEMORY.md Update Required

Add to "Skills Quick Reference" section:

```
- `/archie-focus <target>` — Segmented boot (3–5 segments). Use instead of full /archie-boot when
  scope is known. Targets: consciousness, fleet, dispatch, media_studio, repair_bay, email_manager,
  security_network, backup_manager, account_center, wtf, gov_watch, kso, kbs, billing
```

---

## Rules Files Needed (Gaps)

The following targets lack a `.claude/rules/` file and need one created:

| Target | Rules File Needed | Key content |
|--------|------------------|-------------|
| `security_network` | `.claude/rules/security-network.md` | AdGuard, NPM proxy, Stalwart, compliance scans, V.I.G.I.L. |
| `backup_manager` | `.claude/rules/backup-manager.md` | GFS retention, cloud backup, USB sync, W.A.R.D.E.N. |
| `account_center` | `.claude/rules/account-center.md` | Role hierarchy, invite system, subscription tiers, R.E.S.O.L.V.E. |
| `media_hub` | `.claude/rules/media-hub.md` | Plex/Jellyfin, M.A.V.E.N. probes, SABnzbd gotchas |
| `fleet` | `.claude/rules/fleet.md` | Merge of current `starbase.md` + mesh routing mandate |
| `billing` | `.claude/rules/billing.md` | Stripe service, subscription_service, billing_webhook, unified pricing plan |

The existing rules files already covering: `wtf.md` ✅ `gov-watch.md` ✅ `consciousness.md` ✅ `email-manager.md` ✅ (all created in current session).

---

## Build Sequence

- [ ] **Step 1**: Create missing rules files listed above (6 files)
- [ ] **Step 2**: Update `BOOT_TARGETS` dict in `/archie-focus` skill with canonical target list
- [ ] **Step 3**: Implement segment loader in the skill — each segment type has a loader function
- [ ] **Step 4**: Update MEMORY.md "Skills Quick Reference" to document all available targets
- [ ] **Step 5**: Validate focused boot for 3 targets (gov_watch, wtf, media_studio) — measure actual token use in boot summary
- [ ] **Step 6**: Document in KB as vault_note for future session awareness

---

## Key Gotchas

- **Identity gate is MANDATORY** in focused boot too — `core_identity` segment always loads, gate always fires. Do not skip it.
- **`active_mistakes` must scope to the target** — loading all 62 mistakes defeats the purpose. Pass target as query to `search_knowledge(types=["mistake_learned"], query=target_name, limit=5)`.
- **Do NOT add segment loading to `/archie-boot`** — full boot stays as-is. Focused boot is the new entry point for known-scope sessions.
- **Token count is an estimate** — actual savings vary by how much KB context is returned. Measure on first 3 uses and adjust segment contents accordingly.
