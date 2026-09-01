---
globs: ["kytran-server-manager/**", "kytran-business-suite/**", "kytran-*/**"]
---

# Standalone Extraction Playbook (Established 2026-03-25)

Tiered checklist for pulling any module out of A.R.C.H.I.E. into an independent standalone product.
Every extraction follows this playbook. No exceptions.

## Tier 1 — Must Ship (Blocking Release)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | All features from ARCHIE module transferred and working | Side-by-side route audit, browser test every endpoint |
| 2 | Full LCARS theme matching platform admin modules | Frame blocks with sidebar, elbow corners, accent colors, responsive (480/768/1024px) |
| 3 | Authentication — local auth minimum, SSO-ready `/auth/sso` endpoint stubbed (returns 501) | Login flow works end-to-end |
| 4 | Own database (SQLite default, PostgreSQL option) | Zero dependency on ARCHIE's database |
| 5 | Own static assets (CSS/JS self-contained) | No imports from ARCHIE's shared files |
| 6 | Docker-ready: `Dockerfile` + `docker-compose.yml` with compliance (read-only rootfs, resource limits, pinned tags) | `docker compose up` works from clean clone |
| 7 | README with install, configure, run instructions | Someone unfamiliar can get it running in <10 min |
| 8 | Passes Tier 1 compliance checks from `compliance-standards.md` | No hardcoded secrets, resource limits set, pinned tags |
| 9 | Registered in Code Health scanner | Shows in Consciousness module Code Health tab |
| 10 | **Container DNS override** — `dns: [192.168.1.200, 1.1.1.1]` on any service that reaches external hostnames | Each app-like service in docker-compose.yml has an explicit `dns:` block; postgres/redis-only services may omit |

### Why #10 is mandatory

Host `/etc/resolv.conf` on the hub is Tailscale-owned. Docker's embedded resolver at `127.0.0.11` cherry-picks the first two upstreams (`100.100.100.100` MagicDNS + its IPv6 twin) and **drops** the host's `8.8.8.8` fallback. If MagicDNS's upstream ever SERVFAILs — as happened to AdGuard briefly on 2026-04-14 — containers lose external name resolution entirely while the host stays fine.

That silent failure mode kept Prowlarr blind to `api.nzbgeek.info` for **7 days** until a user reported "Sonarr isn't downloading" on 2026-04-21 (PR #258, vault note #258811). Every standalone that reaches external services needs the explicit DNS block as defence in depth.

Exceptions:
- Database + cache containers (postgres, redis) that only talk to app siblings on the compose network.
- Reverse proxies serving only static local content (e.g. `www_proxy` nginx).

## Tier 2 — Within 30 Days of Ship

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | Auth interconnection — "Sign in with Kytran" OAuth flow | ARCHIE login grants access to standalone |
| 2 | Compliance scanning integrated — runs own relevant rule packs | `/api/compliance/scan` returns results |
| 3 | Live compliance badges on standalone dashboard | SVG badges rendering with real scores |
| 4 | Subdomain with SSL via NPM proxy | `server.kytranempowerment.com` loads over HTTPS |
| 5 | ARCHIE dashboard module replaced with redirect/launch link | Module click opens standalone |
| 6 | Health endpoint for ARCHIE monitoring | `/api/health` returns status + version |
| 7 | Mobile/responsive polish at all breakpoints | Tested at 480px, 768px, 1024px |
| 8 | Code Health shows compliance tier progress | Green/yellow/red badge in Consciousness |

## Tier 3 — Roadmap (Within 90 Days)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | SOC 2 evidence collection + PDF reports | Generated PDF passes manual review |
| 2 | S.H.I.E.L.D. agent integration via Bridge dispatch | AI-powered compliance analysis working |
| 3 | Subscription-gated features (free vs paid) | Feature flags + payment flow tested |
| 4 | Node/Starship integration — deployable on fleet nodes | Standalone runs on node hardware |
| 5 | Agent loop job monitoring standalone health | ARCHIE alerts on standalone downtime |
| 6 | Public product page with pricing | Page live on kytranempowerment.com |

## Extraction Process

1. **Audit** — Read every route, template, feature in the ARCHIE module. Document what exists.
2. **Gap analysis** — Compare against standalone. List missing, different, extra.
3. **Migrate** — Transfer missing features. Adapt to standalone architecture.
4. **Theme** — Apply full LCARS frame styling (sidebar + elbows + header bar + segments).
5. **Auth bridge** — SSO endpoint stub (Tier 1) or full OAuth (Tier 2).
6. **Code Health** — Register in `STANDALONE_PRODUCTS` in `code_metrics_service.py`.
7. **Compliance scan** — Run through applicable rule packs. Fix failures.
8. **Redirect** — Replace ARCHIE module with launch link.
9. **Verify** — Browser test all features, compliance green, badges live, Code Health reporting.

## Platform-Integration Env Contract (STANDARD — established 2026-06-11, owner mandate)

Every standalone container that talks to hub services MUST satisfy ALL FOUR rules.
Violating any one of them produced a real outage (INTERNAL_API_KEY 2026-05-26 tier-push
failures; AC_API_URL 2026-06-11 market paywall shown to the OWNER).

**1. The contract vars** — declared in compose for every product container:

| Var | Purpose | Mesh default |
|-----|---------|--------------|
| `BRIDGE_URL` | DHQ dispatch | `http://100.64.0.4:3000` |
| `AC_API_URL` | Account Center billing gate (`has_product_access`) | `http://100.64.0.4:3000` |
| `AC_INTERNAL_TOKEN` | AC auth (when required) | empty passthrough |
| `INTERNAL_API_KEY` | hub→standalone tier pushes (`/api/internal/set-tier`) | empty passthrough |

**2. Compose passthrough is MANDATORY when there is no `env_file:`** — a correct value
in `.env` does NOTHING unless the var is listed in the service's `environment:` block:
`- AC_API_URL=${AC_API_URL:-http://100.64.0.4:3000}`. (market + civic composes have no
`env_file:`; legal + gov do. Check before assuming.)

**3. Code defaults = MESH IPs, never LAN, never public.** `192.168.1.200` is unreachable
from Citadel/outposts (dormant subnet route) → 5s timeout → a fail-closed billing gate
paywalls EVERYONE including the owner. Public hostnames hit the 60s CDN cap. Default
`os.getenv("AC_API_URL", "http://100.64.0.4:3000")` — fixed in all 4 watch repos 2026-06-11.

**4. Verify the RUNTIME env, not the files.** The post-deploy trio:
```bash
grep VAR /opt/archie-products/<p>/.env                      # 1. value staged
grep VAR /opt/archie-products/<p>/docker-compose.yml        # 2. passthrough exists
docker inspect <container> -f '{{range .Config.Env}}{{println .}}{{end}}' | grep VAR  # 3. THE TRUTH
```
Only #3 is authoritative — #1 and #2 looked perfect during the market outage while the
container ran without the var.

**Paywall gates (billing_gate skill)**: read `session.get("kytran_user")` (kytran_auth) —
NEVER flask-login `current_user` unless the app actually initializes a LoginManager
(market's didn't → AttributeError 500 on every gated page = the 2026-06-11 sign-in
outage). Exempt all `/api/` paths — they carry their own auth (service token / X-Internal-Key).

## Common traps (learned the hard way)

### CSS dependency tree — ship the WHOLE stack

`platform_v2/templates/base.html` loads **2 CDN stylesheets + 15 local CSS files** in a specific order. The module's own stylesheet (`<module>.css`) assumes every one of those upstream files has already declared its tokens and resets. Shipping only `<module>.css` + a couple of LCARS chrome files leaves the UI stuck in light-mode-forever (body-level dark tokens never declared, browser defaults win).

⚠️ **CORRECTED 2026-09-01 — the list below previously did not match `base.html`.** It claimed 16 files, put `base.css` SECOND, and listed `category-nav.css` and `lcars-header.css`, **neither of which base.html loads**. Since this section's whole point is that a wrong order leaves a standalone visually broken, that made the trap it warns about. Re-derive from the template, never from memory:
`grep -oP 'href="[^"]*\.css[^"]*"' platform_v2/templates/base.html`

Audit your standalone base template against this list before considering a module "extracted" — **this is base.html's real order**:

```
(CDN) bootstrap@5.3.2 + bootstrap-icons@1.11.1   — loaded FIRST, before all of ours
theme.css              — 268 --archie-* tokens; IS the default 'lcars-classic' theme
animations.css         — LCARS transitions + transforms
archie-breakpoints.css — responsive breakpoints
components.css         — semantic components + a Tailwind-shaped utility layer
lcars-frames.css       — elbow corners + frame borders
lcars-modals.css       — bm-overlay + bm-shell modals
admin-ops.css          — admin page chrome (global, not module-scoped)
department-ops.css     — department/station chrome (global)
light-mode.css         — re-declares --archie-* under body.light-mode (see below)
themes/<theme>.css     — ONLY when the theme is not lcars-classic
layouts/<family>-layout.css — corporate | elegant | minimal
mobile.css             — 480/768/1024px overrides
agent-badge.css
archie-chat.css
base.css               — html/body reset + typography — LOADED LAST, deliberately
<module>.css           — module-specific styles
```

⚠️ **`base.css` is LAST, not second.** Its resets and typography are meant to win over the component layers; hoisting it to the top (as this file used to show) silently changes the cascade.

⚠️ **`.row` / `.col-*` come from the Bootstrap CDN, not from us.** Our CSS defines `.btn` and `.card` but NOT `.row` — a standalone that drops the CDN loses its grid.

**`light-mode.css` is safe to ship on its own** — 114 of its 118 rule blocks are scoped to `body.light-mode` and it has zero unscoped `:root`/`body` rules, so it is inert until the class is set. ⚠️ This paragraph previously said the opposite ("do NOT ship it without a `themes/<theme>.css` override — it wins on every selector"); that is false and would have led to shipping an unnecessary theme override that DOES override the default look. base.html ships light-mode.css unconditionally.

### Asset dependency tree — not just CSS

Same discipline for JS + icons + manifest:

```
js/<module>.js         — the module JS
js/<module>-sw.js      — if the module is a PWA
js/lcars-header.js     — required by lcars-header.html include
manifest.json          — required by <link rel="manifest">
icons/<module>-*.png   — all sizes referenced from manifest + html
```

Service workers are booby-trapped: `cache.addAll()` fails the ENTIRE install if any single entry 404s, leaving the PWA silently broken. Audit the SW's `STATIC_ASSETS` list against what actually exists in the standalone build.

### External CDN scripts

If platform base loads anything from a CDN (Lucide icons, Bootstrap, fonts), make sure the standalone base loads them too. Platform dependencies like `https://unpkg.com/lucide@latest` aren't installed automatically — they're `<script>` tags the standalone base must repeat.

### Negative cache

Users who visited during the "built-but-assets-missing" window may have 404s negatively cached in their browser. Either ship `Cache-Control: no-cache, must-revalidate` on all responses until the extraction stabilises (transitional), or use hash-based filenames for static assets (production pattern).

### Full QA loop — don't trust a single screen state

Playwright "it renders" isn't enough — log in, navigate every main nav tab, check the console for 404s on each route. Compare light-mode vs dark-mode visually. The CSS drift in Media Hub went unnoticed for ~4 PRs because only one screen state was tested against a cached browser.

## Active Standalone Products

| Product | Port | Path | Tier | Status |
|---------|------|------|------|--------|
| Kytran System Operations | 8085 | `/mnt/archie_brain/kytran-server-manager` | 1 | In Progress |
| Kytran Business Suite | 8091 | `/mnt/archie_brain/kytran-business-suite` | 1 | Phase 1 Complete |
| C.R.E.E.D. Governance | 8086 | `/mnt/archie_brain/kytran-creed` | 1 | Deployed (Decision #438) |
| Media Hub | 8105 | `/mnt/archie_brain/standalone/media_hub` | 1 | Live 2026-04-19 at media.kytranempowerment.com |
