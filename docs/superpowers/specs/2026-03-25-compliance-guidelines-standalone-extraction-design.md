# Compliance Guidelines + Standalone Extraction Playbook

**Date**: 2026-03-25
**Project**: #193 — Kytran System Operations — Standalone Product + Compliance Engine
**Status**: Design Approved
**Scope**: Platform-wide compliance standards + tiered extraction playbook for standalone products

---

## Problem Statement

A.R.C.H.I.E. achieved 100% compliance across 178 automated checks (CIS, STIG, HIPAA, SOC 2, Network). This standard must be codified and enforced going forward — not just for the platform, but for every standalone product extracted from it.

The System Operations module is the first standalone extraction (Kytran System Operations, port 8085). It needs:
- All features migrated from the ARCHIE module
- Full LCARS theme matching other admin modules
- Authentication interconnection with ARCHIE's Google OAuth
- Code Health visibility in the Consciousness module
- Compliance scanning of its own

A repeatable playbook is needed so future extractions (node system, other modules) follow the same standard.

---

## Deliverables

### Deliverable 1: `compliance-standards.md` (Rules File)

**Location**: `.claude/rules/compliance-standards.md`
**Scope**: All platform work, every session

#### Section 1: Security Hardening Standards
- All Docker containers: read-only rootfs (`read_only: true`), no `--privileged`, explicit capability drops
- Resource limits on every container (CPU + memory in docker-compose)
- No secrets in environment variables or code — use Docker secrets or `.env` files (never committed)
- DB passwords via `os.getenv()` only, never hardcoded
- TLS required for all external-facing services (NPM proxy + SSL cert)
- UFW firewall: default deny inbound, explicit allow rules only
- SSH: key-only authentication, no root login, fail2ban active
- Container images: pinned tags (no `:latest` in production), trusted base images only
- Tmpfs mounts for writable temp directories inside read-only containers

#### Section 2: Code Quality Standards
- Route splitting per ADR-045 (`register_*_routes` pattern) — no single route file over 600 lines
- Service extraction for business logic — routes are thin HTTP handlers calling service functions
- All DB connections use `try/finally: conn.close()` or context manager — no connection leaks
- Specific exception handling — no bare `except:`, catch `Exception` minimum
- No direct Ollama inference from modules — Bridge dispatcher only (ADR-013)
- Black formatting enforced via pre-commit hook — re-stage after first commit attempt fails
- No hardcoded IPs or ports — use config/env vars
- Import from shared modules (`from db import get_db`) — no local `get_db()` redefinitions

#### Section 3: Compliance Scanning Requirements
- Any customer-facing or infrastructure service must have a compliance scan profile
- Rule packs are JSON-driven — stored in `rule_packs/` directory, add rules without code changes
- Rule format: `rule_id`, `severity` (low/medium/high), `check_type`, `fix` with risk level, `soc2_mapping`
- Scans auto-run every 6 hours via agent loop job
- Findings tracked in `compliance_scan_results` with severity, status (pass/fail/error/not_applicable), and remediation path
- One-click remediation via host command client for automatable fixes

#### Section 4: Public Compliance Posture
- Live SVG badges for all applicable frameworks (STIG, SOC 2, HIPAA, CIS, Network)
- Badge scoring: Green (90%+), Blue (80%+), Yellow (70%+), Red (<60%)
- Grade scale: A+ (95%), A (90%), B+ (85%), B (80%), C (70%), D (60%), F (<60%)
- Trust center page presence for any product offered as a service
- SOC 2 evidence collection mapped to Trust Service Criteria (5/5 TSC)
- Badge scores auto-refresh from latest scan results
- Competitor comparison page updated when new products ship

---

### Deliverable 2: `standalone-extraction.md` (Extraction Playbook)

**Location**: `.claude/rules/standalone-extraction.md`
**Scope**: Any module being extracted from ARCHIE into a standalone product

#### Tier 1 — Must Ship (Blocking Release)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | All features from ARCHIE module transferred and working | Side-by-side route audit, browser test every endpoint |
| 2 | Full LCARS theme matching platform admin modules | Frame blocks, `bm-` class system, accent colors, responsive breakpoints (480/768/1024px) |
| 3 | Authentication system — local auth minimum, SSO-ready endpoint stubbed | Login works, `/auth/sso` endpoint returns 501 (ready for Tier 2) |
| 4 | Own database (SQLite default, PostgreSQL option) | No dependency on ARCHIE's database |
| 5 | Own static assets (CSS/JS extracted) | No imports from ARCHIE's shared files |
| 6 | Docker-ready: `Dockerfile` + `docker-compose.yml` | `docker compose up` works from clean clone |
| 7 | README: install, configure, run | Someone unfamiliar can get it running |
| 8 | Passes Tier 1 compliance checks | Read-only rootfs, no hardcoded secrets, resource limits, pinned tags |
| 9 | Registered in Code Health scanner | Shows in Consciousness module with metrics |

#### Tier 2 — Within 30 Days of Ship

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | Auth interconnection — "Sign in with Kytran" OAuth flow | ARCHIE login grants access to standalone |
| 2 | Compliance scanning integrated — runs own relevant rule packs | `/api/compliance/scan` returns results |
| 3 | Live compliance badges on standalone dashboard | SVG badges rendering with real scores |
| 4 | Subdomain configured with SSL via NPM proxy | `server.kytranempowerment.com` loads over HTTPS |
| 5 | ARCHIE dashboard module replaced with redirect/launch link | Clicking System Ops in ARCHIE opens standalone |
| 6 | API health endpoint for ARCHIE to query | `/api/health` returns status + version |
| 7 | Mobile/responsive polish | Tested at 480/768/1024px breakpoints |
| 8 | Code Health shows compliance tier progress | Green/yellow/red badge in Consciousness |

#### Tier 3 — Roadmap (Within 90 Days)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | SOC 2 evidence collection + PDF reports | Generated PDF passes manual review |
| 2 | S.H.I.E.L.D. agent integration via Bridge dispatch | AI-powered compliance analysis working |
| 3 | Subscription-gated features (free vs paid tiers) | Feature flags working, payment flow tested |
| 4 | Node/Starship integration — deployable on fleet nodes | Standalone runs on node hardware |
| 5 | Agent loop job monitoring standalone health | ARCHIE alerts on standalone downtime |
| 6 | Public product page with pricing on kytranempowerment.com | Page live, pricing accurate |

#### Extraction Process (Step by Step)

1. **Audit** — Read every route, template, and feature in the ARCHIE module. Document what exists.
2. **Gap analysis** — Compare against standalone. List missing, different, and extra features.
3. **Migrate** — Transfer missing features. Adapt to standalone's architecture, don't copy-paste.
4. **Theme** — Apply full LCARS frame styling matching other admin modules (`bm-` classes, accent colors, frame blocks).
5. **Auth bridge** — Wire up SSO endpoint stub (Tier 1) or full OAuth flow (Tier 2).
6. **Code Health registration** — Add standalone to `STANDALONE_PRODUCTS` registry in `code_metrics_service.py`.
7. **Compliance scan** — Run standalone through applicable rule packs. Fix all failures.
8. **Redirect** — Replace ARCHIE module with launch link to standalone URL.
9. **Verify** — Browser test all features, compliance scan green, badges live, Code Health reporting.

---

### Deliverable 3: Code Health Integration for Standalone Products

**Files Modified**:
- `platform_v2/services/code_metrics_service.py` — add `STANDALONE_PRODUCTS` registry + scanning
- `platform_v2/tools/consciousness/code_health_routes.py` — expose standalone metrics
- `platform_v2/static/js/consciousness.js` — render standalone section in UI

#### Scanner Extension

Add a `STANDALONE_PRODUCTS` list to `code_metrics_service.py`:

```python
STANDALONE_PRODUCTS = [
    {
        "name": "Kytran System Operations",
        "path": "/mnt/archie_brain/kytran-server-manager",
        "module_key": "kytran_system_operations",
        "tier": 1,
        "compliance_profile": "server-management",  # maps to: ubuntu-stig, docker-stig, network-stig, cis-ubuntu, hipaa

    }
]
```

`scan_codebase()` loops through `STANDALONE_PRODUCTS` in addition to platform modules. Each standalone appears in `per_module` JSONB with a `[STANDALONE]` prefix.

#### UI Section

Standalone products get their own collapsible group in the Code Health module table:
- Separated from ARCHIE modules visually (different header color — e.g., gold accent)
- Each standalone shows: file count, line count, language breakdown
- Compliance tier badge: green (Tier 1 complete), yellow (in progress), red (not started)
- Mini compliance score from latest scan results
- Link to standalone's own compliance dashboard (when Tier 2 complete)

#### Health Cross-Reference

Code Health route queries compliance scan results for each registered standalone:
- Latest scan score
- Last scan timestamp
- Number of passing/failing checks
- Tier completion status (checklist progress)

---

### Deliverable 4: KB Entries

Both documents stored as `vault_note` entries:
- **Title**: "Compliance Standards — Platform-Wide Security & Quality Rules"
- **Title**: "Standalone Extraction Playbook — Tiered Checklist for Module Independence"
- **Knowledge type**: `vault_note`
- **Tags**: `compliance`, `guidelines`, `standalone`, `extraction`
- **Importance**: 0.95 (high — these are governance documents)

Searchable via `mcp search_knowledge` by any agent or session.

---

## Application to System Operations Standalone (KSM)

### Current State (6/26 tasks complete)
- Route split done (ADR-045)
- Standalone package exists on GitHub
- Compliance engine built (178 rules, 5 packs, 92.8% → 100%)
- Compliance UI done (Vanta-style dashboard, badges, PDF)
- Website pages published (trust center, pricing, competitors)
- Theme system + Starship integration done

### Known Gaps (from exploration)
| Gap | Tier | Priority |
|-----|------|----------|
| NPM Proxy routes missing from standalone | Tier 1 | High |
| Docker Swarm support missing | Tier 1 | Medium |
| VLAN management missing | Tier 1 | Medium |
| LCARS theme doesn't match admin modules (no frame blocks) | Tier 1 | High |
| Auth is local-only, no SSO stub | Tier 1 | High |
| Not in Code Health scanner | Tier 1 | Medium |
| No "Sign in with Kytran" OAuth | Tier 2 | — |
| No live badges on standalone dashboard | Tier 2 | — |
| No subdomain (server.kytranempowerment.com) | Tier 2 | — |
| ARCHIE module not redirected | Tier 2 | — |
| No SOC 2 evidence/PDF in standalone | Tier 3 | — |
| No S.H.I.E.L.D. Bridge integration | Tier 3 | — |
| No subscription gating | Tier 3 | — |
| No node/Starship deployment | Tier 3 | — |

---

## Out of Scope

- Automated enforcement via agent loop jobs (future enhancement)
- Per-standalone compliance dashboards beyond what Tier 2 defines
- Pricing/subscription model business decisions
- Node system rebuild (separate project, noted for future planning)
- Other module extractions (playbook covers them, but only KSM is active now)

---

## Success Criteria

1. Both rules files committed and loading in every Claude session
2. Both KB entries stored and searchable
3. KSM measured against Tier 1 checklist — all gaps identified with tasks
4. Code Health scanner includes KSM with compliance cross-reference
5. Future module extractions can follow the same playbook without reinventing
