# What The Fact + TheNews Consolidation — Design

**Date**: 2026-04-18
**Projects affected**: #259 What The Fact, #260 WTF + TheNews Integration
**Status**: spec complete, pending user review → writing-plans

---

## Context

Two overlapping initiatives exist in the platform today:

1. **TheNews** (`thenews.kytranempowerment.com`) — standalone Docker container on the US Outpost VPS at port 8103. Container name `kytran_news`. Intended as a news product but, per user, "had a really bad start" and is effectively broken / unused. Has minimal content, no meaningful traffic.

2. **What The Fact (WTF)** — planned as "Canada's first AI-powered news platform built on radical transparency" with two domains:
   - `what-the-fact.com` — consumer news with bias detection and fact-checking (currently on Hostinger shared hosting, limited)
   - `what-the-fact.tech` — transparency + developer platform (audit trails, API, methodology docs — not yet active)

The overlap was already flagged in planning project #260 ("WTF + TheNews Integration — Standalone Alignment"). Relationship clarified during brainstorm: TheNews was intended as the **ingestion/feed backend**, WTF as the **consumer-facing product**. Since TheNews never fulfilled that role, the pipeline exists in name only.

Secondary constraint: Hostinger shared is limited, so WTF must migrate off before any real traffic lands. Long-term vision is distributed ingestion across the outpost fleet for regional/international coverage.

## Decision (Approach 1 — Clean Cut)

Retire TheNews entirely. Rebuild the pipeline as WTF-internal services. No migration of TheNews code or data (nothing worth preserving). Port 8103 is freed and reused by WTF's consumer service. Hard DNS cutover (no redirect grace period) — `thenews.kytranempowerment.com` record deleted.

Two other approaches considered and rejected:
- **Graceful phased migration** — over-engineered for a broken product with no traffic worth preserving.
- **Ingestion-first, sites later** — leaves `what-the-fact.com` on Hostinger shared longer; doesn't solve the "limited hosting" constraint quickly.

## Target Architecture

### Services (3 containers in one WTF stack)

| Service | Port | Domain | Purpose |
|---|---|---|---|
| `wtf-consumer` | 8103 (reused) | `what-the-fact.com` | Public news reader with bias scores, fact-check summaries, source transparency. Guest-readable; no login required. |
| `wtf-tech` | 8104 (new) | `what-the-fact.tech` | Transparency + developer portal. Per-article audit trails, methodology docs, read-only API (internal-only for MVP). Kytran SSO for authenticated routes. |
| `wtf-ingest` | internal | — | News scrapers (RSS / public APIs), canonical article normalizer, bias pipeline. Designed fleet-ready so it can be deployed to outpost nodes later for regional ingestion — no re-architecture needed. |

### Data flow

```
    [CBC RSS / future sources]
              │
              ▼
        wtf-ingest
              │
              ├── canonical article → shared PostgreSQL (articles, bias_scores, fact_checks, audit_trail, source_registry)
              └── bias/fact-check decisions → C.R.E.E.D. event emission
              ▼
    wtf-consumer ◄── reads → DB
    wtf-tech     ◄── reads → DB (+ audit trail, API routes)
```

### Infrastructure placement

- **Host**: US Outpost VPS (`76.13.107.109`). Same host that runs market/civic/legal/gov watch products, per the existing Watch-series convention.
- **Reverse proxy**: Caddy on the VPS — auto-HTTPS via Let's Encrypt, two server blocks matching the Watch-series template.
- **DNS**: `what-the-fact.com` A → 76.13.107.109; `what-the-fact.tech` A → 76.13.107.109. Managed via the Hostinger MCP.

### Authentication & Branding

- **SSO**: reuse `kytran_auth.py` SDK (same pattern as KBS / KSO / Market Watch / Civic Watch / Legal Watch / Gov Watch). No custom auth. Two OAuth clients seeded in migration 305:
  - `wtf-consumer` — guest reads allowed; auth only for personalization / saved articles (future).
  - `wtf-tech` — auth-gated for API token issuance and developer dashboard.
- **Landing pages**: match Watch-series template (same LCARS-adjacent styling, same Caddy structure). Consumer site shows public news list; tech site shows "Sign in with Kytran Empowerment" CTA.
- **Product family**: WTF registered alongside the existing Watch Series in:
  - `platform_v2/services/code_metrics_service.py` — `STANDALONE_PRODUCTS` registry
  - `platform_v2/module_registry.py` — `MEDIA_OUTREACH` category next to `kytran_market_watch`, `kytran_civic_watch`, etc.
  - `.claude/rules/operational-state.md` — product registry table + DNS list
  - `platform_v2/services/infra_heartbeat_service.py` — `CRITICAL_CONTAINERS` (V.I.G.I.L. heartbeat observer auto-recovers on outage, Project #272 Phase 2)

## Migration Sequence

### Phase A — Retire TheNews (cleanup only, no build)

1. **VPS cleanup** (`76.13.107.109`):
   - `docker stop kytran_news && docker rm kytran_news`
   - Remove `kytran_news` stanza from VPS `docker-compose.yml`
   - Delete `thenews.kytranempowerment.com` Caddy block, `caddy reload`
2. **Hub cleanup**: search + remove / update references to `kytran_news` / `thenews` in:
   - `.claude/rules/operational-state.md`
   - `platform_v2/services/code_metrics_service.py` (`STANDALONE_PRODUCTS`)
   - `platform_v2/services/infra_heartbeat_service.py` (`CRITICAL_CONTAINERS`)
   - `docker-compose.yml` — remove `/mnt/archie_brain/website/thenews.kytranempowerment.com` mount line (and any standalone path)
3. **DNS**: delete `thenews.kytranempowerment.com` A record via Hostinger MCP
4. **Knowledge base**: store a vault_note documenting the retirement + update MEMORY.md

### Phase B — Stand up WTF stack (new build)

5. Create repo at `/mnt/archie_brain/what-the-fact/`:
   ```
   what-the-fact/
   ├── docker-compose.yml
   ├── Dockerfile.ingest
   ├── Dockerfile.consumer
   ├── Dockerfile.tech
   ├── ingest/        # scrapers + normalizer + bias pipeline
   ├── consumer/      # reader app (Flask + Jinja, matching platform stack)
   ├── tech/          # transparency portal + read-only API
   ├── shared/        # article schema, DB models, SSO helpers
   ├── migrations/    # DB schema for articles / bias_scores / fact_checks / audit_trail / source_registry
   └── README.md
   ```
6. Schema migration — article store + bias scores + fact-check records + audit trail + source registry.
7. Ingest: CBC English RSS as the single MVP source; canonical article normalizer; simple rule-based bias heuristic.
8. Consumer site: list view + article detail with bias badge, source attribution, fact-check summary.
9. Tech site: per-article transparency page with full audit trail + methodology doc; Kytran SSO gate on authenticated routes.
10. Landing pages + shared styling matching the Watch-series template.

### Phase C — Deploy

11. Push images to VPS, add WTF stack to VPS `docker-compose.yml` at ports 8103 + 8104.
12. Add Caddy stanzas for `what-the-fact.com` → 8103 and `what-the-fact.tech` → 8104. `caddy reload`.
13. DNS: point `what-the-fact.com` + `what-the-fact.tech` A records to `76.13.107.109` via Hostinger MCP.
14. Once the VPS container is serving, unhost `what-the-fact.com` from Hostinger shared.
15. Wire C.R.E.E.D. event emission from `wtf-ingest` to the platform governance channel.

### Phase D — Ship + observe

16. Verify live: `https://what-the-fact.com` and `https://what-the-fact.tech` return the expected pages with Let's Encrypt certs issued.
17. Add WTF containers to `CRITICAL_CONTAINERS` in `infra_heartbeat_service.py` — V.I.G.I.L. heartbeat (Project #272 Phase 2) now watches them.
18. Add WTF to `STANDALONE_PRODUCTS` in `code_metrics_service.py` — Code Health scanner picks up the codebase.
19. Close project #260 (WTF + TheNews Integration) — superseded.
20. Update `MEMORY.md` product table + `operational-state.md` product registry.

**Phase A and B can run in parallel.** Phase C blocks on B. Phase D blocks on C.

## Scope

### In scope (this consolidation)

- Everything in Phases A–D above
- 1 Canadian news source (CBC English RSS) at MVP
- Simple rule-based bias heuristic
- Kytran SSO integration (using existing SDK — do not roll custom auth)
- Watch-series landing / styling consistency
- VPS deployment at ports 8103 + 8104
- Full infra integration (heartbeat, code health, compliance badge, product registry)

### Out of scope (explicit deferrals)

| Deferred item | Why |
|---|---|
| Multi-source ingestion (Global News, Toronto Star, La Presse, Radio-Canada French, CBC French) | MVP = CBC English. Add incrementally once schema + pipeline proven |
| Distributed outpost deployment of `wtf-ingest` | Design is fleet-ready; actual rollout waits for node fleet readiness |
| Real-time article streaming (WebSocket push) | Polling refresh first; push later |
| ML bias models vs. rule-based | Ship with heuristic; ML is a separate project |
| Fact-check partner integrations (Snopes, AP Fact Check, PolitiFact) | Needs legal + rate-limit review |
| Paid subscription gating | Free-access MVP; reuse KBS tier gating pattern (#2018 Phase 1) when monetization needed |
| Public API launch on `.tech` | Internal-only during MVP; needs docs, rate limits, API keys |
| User-generated content (comments, submissions) | Not in vision — editorial transparency focus |
| Mobile apps | Web-first, responsive design covers both |
| `kytran_auth.py` SDK consolidation | Separate task #2064, does not block here |
| Compliance certification beyond Watch-series Tier 2 | Inherits existing posture |
| Multilingual UI (i18n) | English-only MVP; platform translation system can be added later |

### Follow-up tasks to file after this ships

1. WTF · Add source N (one task per additional Canadian source)
2. WTF · ML bias scoring v2 (replace heuristic)
3. WTF · Fact-check partner integration
4. WTF · Public API launch on `.tech` (docs + rate limits + keys)
5. WTF · Deploy `wtf-ingest` to first outpost (fleet scaling validation)
6. WTF · Paid tier integration once KBS gating Phase 2 lands
7. WTF · i18n pass (French Canadian first)

## Testing Strategy

- **Ingest**: unit tests for the RSS parser + canonical normalizer. Integration test that persists one article end-to-end to the DB.
- **Bias pipeline**: golden-file test — 10 known articles, expected bias band per article.
- **Consumer site**: HTTP smoke test on each route + one Playwright pass on the Watch-series landing template to confirm visual alignment.
- **Tech site**: API contract test on each read-only endpoint, plus Kytran SSO round-trip test on authenticated routes.
- **Infra**: V.I.G.I.L. heartbeat exercised by killing each container and verifying the Tier-2 restart approval fires (Project #272 Phase 2 flow).

## Error Handling

- **Ingest failure** (source offline / rate limit) → log, emit autonomy_loop_log warning row, skip the article, continue. No hard failure on single-source blip.
- **DB write failure** → retry with exponential backoff, then dead-letter the article to a `failed_ingest` table for manual review.
- **Consumer / tech 5xx** → generic error page with link to status. Kytran SSO failures follow the existing `kytran_auth.py` redirect-to-login pattern.
- **Caddy cert issuance failure** → Caddy's own retry; alert via V.I.G.I.L. heartbeat if the service stays unreachable for >5 min.

## Risks / Open Questions

- **Hostinger unhost timing** — during the cutover window (Phase C step 14), there's a DNS propagation gap where Hostinger may still serve the old static site while DNS updates. Accept a ~1hr gap; worst case both serve identical "coming soon" during that window.
- **TheNews content preservation** — spec assumes no content worth preserving. If `kytran_news` container does hold any unique articles or configuration, they're lost at `docker rm`. Mitigation: Phase A step 1 can `docker commit` to a backup image first, kept for 30 days.
- **Port 8103 reuse** — document clearly in `operational-state.md` that port 8103 moved from `kytran_news` to `wtf-consumer`. Any external references to the old mapping will break.

---

## Checklist Hand-off to writing-plans

When moving to implementation planning, the plan document should cover:

- [ ] Phase A tasks (VPS + hub cleanup, DNS deletion, KB update)
- [ ] Phase B tasks (scaffold, migrations, 3 Dockerfiles, ingest MVP, consumer + tech sites, landing templates)
- [ ] Phase C tasks (push, compose, Caddy, DNS, Hostinger unhost)
- [ ] Phase D tasks (verify, heartbeat, Code Health, project close-out)
- [ ] Follow-up tasks filed in DB (items 1-7 above)
- [ ] Verification steps per phase (how we know it worked)
