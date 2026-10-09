---
description: Load focused context for a specific module or system — lightweight alternative to /archie-boot when you already know what you're working on. Saves ~15k context tokens vs full boot.
argument-hint: <target> (consciousness|fleet|dispatch|department_hq|media_studio|repair_bay|email_manager|security_network|backup_manager|account_center|billing|wtf|gov_watch|media_hub|kso|kbs|creed|website)
---

# A.R.C.H.I.E. Focus — Segmented Module/System Boot

**Target: $ARGUMENTS**

Use this instead of `/archie-boot` when you already know what system you're working on. Loads ONLY the relevant context — saves ~15k context tokens vs full boot.

If no target was given, ask the user which target to focus on (list below) and stop.

## Usage

```
/archie-focus consciousness       — Knowledge base, KB loops, Dev HQ
/archie-focus fleet               — Mesh nodes, A.R.M.A.D.A., OTA, node lifecycle
/archie-focus dispatch            — DHQ dispatcher, capability routing, orchestration
/archie-focus department_hq       — Full DHQ module (all 12 tabs)
/archie-focus media_studio        — Media Studio, ComfyUI, portraits, providers
/archie-focus repair_bay          — P.R.O.B.E., QA, proposals, deploy gate
/archie-focus email_manager       — Email Manager, mailboxes, Stalwart
/archie-focus security_network    — V.I.G.I.L., compliance, DNS, AdGuard
/archie-focus backup_manager      — W.A.R.D.E.N., backups, GFS retention
/archie-focus account_center      — Users, roles, invites, API keys, R.E.S.O.L.V.E.
/archie-focus billing             — subscription_plans, tier vocab, billing handlers, bundles
/archie-focus wtf                 — What The Fact, bias, VPS containers, XSS rules
/archie-focus gov_watch           — Gov Watch, P.R.O.C.U.R.E., tenders, tier sync
/archie-focus media_hub           — Media Hub standalone (:8105) + platform module, M.A.V.E.N.
/archie-focus kso                 — Kytran System Operations, compliance, B.A.S.E.
/archie-focus kbs                 — Kytran Business Suite, plugins, billing
/archie-focus website             — kytranempowerment.com Claude-Design port + static deploy
```

## What This Loads (per target)

### Step 1: Rules file
Load the relevant `.claude/rules/` file for the target:
- consciousness → `consciousness.md` + `project-knowledge.md`
- fleet → `fleet.md` (mesh node map, OTA, K.I.N., node lifecycle)
- dispatch / department_hq → `department-hq-dispatch.md` + `fleet.md`
- media_studio → `creative-studios.md`
- repair_bay → `repair-bay.md`
- email_manager → `email-manager.md`
- security_network → `security-network.md` + `compliance-standards.md`
- backup_manager → `backup-manager.md`
- account_center → `account-center.md`
- billing → `billing.md`
- wtf → `wtf.md`
- gov_watch → `gov-watch.md`
- media_hub → `media-hub.md`
- kso → `standalone-extraction.md`
- kbs → `billing.md` + `standalone-extraction.md`
- creed → `standalone-extraction.md`
- google_work_suite / saas_manager / civic_watch / legal_watch / market_watch → `saas-services.md` + `operational-state.md`
- website → **not** a `.claude/rules/` file — read `website/kytranempowerment.com/.design-sync/PORT-STATUS.md`
  (the live page-by-page `todo`/`nav`/`pr`/`merged`/`live` tracker), plus `conventions.md`
  + `NOTES.md` in the same directory. Report the live/nav/todo/no-design-file counts from
  PORT-STATUS.md directly in the Step 5 summary — don't just say "see the tracker."
  **Two facts from that tracker that cost real incidents when forgotten**: (1) this is a
  static Hostinger host with **no CI/webhook** — a merge to `main` does NOT reach production;
  deploy is `scripts/publish_website.sh` + `mcp__hostinger-api__hosting_deployStaticWebsite`
  (full-site zip replace), and nothing may be marked `live` without a real post-deploy browser
  check. (2) Hostinger's CDN caches CSS/JS at `max-age=604800` per exact URL+query — **bump the
  sitewide `?v=` cache-buster on any deploy that touches shared CSS/JS**, or different visitors
  see different versions of the site for up to 7 days (PR #3461's root cause).
  **Claude Design page mockups (`.dc.html` handoffs) are NOT stored in this repo** — they come
  from a separate Claude Design project reached via the `/design-sync`-gated `DesignSync` tool
  or a link the owner provides; don't fabricate page content "to match Design" without actually
  having the source in front of you — every prior port in the tracker was verified against
  Design's literal computed-style values, never approximated.

### Step 2: KB search for this module
Call `mcp__archie__search_knowledge(query="<target> module capability", category="module_capability", limit=3)`

If KB returns empty (embedding cold):
> ⚠️ KB search returned 0 results — embedding model cold. Text search only. Run:
> `mcp__archie__search_knowledge(query="<target>", limit=5)` (text-only fallback)

### Step 3: Mistakes for this module
Call `mcp__archie__search_knowledge(query="<target> mistake error", types=["mistake_learned"], limit=5)`

### Step 4: Active tasks for this area
Call `mcp__archie__get_my_tasks(status="in_progress")` — filter results for the target module name.

### Step 5: Module summary
Print a focused summary:

```
## Focused on: <TARGET>
- **Rules file loaded**: <file>
- **KB context**: <N entries found / embedding cold warning>
- **Relevant mistakes**: <list or "none found">
- **Active tasks**: <list or "none in progress">
- **Key agents**: <relevant director + any module chat overlay agent>
- **Critical gotchas**: <from docs/generated/module-capability-index.md>
- **Ready**: Yes/No
```

## Key Agent Assignments (for delegation)

| Module/System | Agent | Capability |
|--------------|-------|-----------|
| consciousness / KB | C.O.D.E.X. | `documentation`, `knowledge_analysis` |
| fleet / armada | B.A.S.E. (infra) / K.I.N. (welfare) | `infrastructure`, `welfare` |
| dispatch debugging | S.P.E.C.T.R.A. | `analyze` |
| media_studio / portraits | M.U.S.E. | `creative`, `image_generation` |
| repair_bay / QA | P.R.O.B.E. | `code_review`, `debug` |
| security / compliance | V.I.G.I.L. | `security`, `compliance` |
| backup / ops | W.A.R.D.E.N. | `backup_verify`, `user_audit` |
| email / support | R.E.S.O.L.V.E. | `support` |
| gov_watch / tenders | P.R.O.C.U.R.E. | `tender_match`, `bid_draft` |
| code / engineering | F.O.R.G.E. | `code`, `debug` |
| research / KB analysis | D.A.R.W.I.N. | `research` |

## Delegation from Focus Context

Once focused, delegate work to the cluster:

```python
# From Claude CLI (MCP):
mcp__archie__delegate_task(
    capability='<from table above>',
    reason='<what you need done>',
    delegation_source='claude'
)

# This routes: Claude → delegate_task_worker → DHQ dispatcher
#   → CAPABILITY_DEPARTMENT_MAP → home dept director
#   → fleet_resource_router → best cluster node (mesh 100.64.0.x)
#   → task_execution_log → result back
```

Known-tool shortcuts (skip LLM, direct service call):
- `run_qa_suite` — trigger P.R.O.B.E. QA
- `check_dep_drift` — F.O.R.G.E. dependency audit
- `health_check` / `check_platform_health` — platform status
- `run_misroute_audit` — S.P.E.C.T.R.A. dispatch audit

## Consciousness KB Access

The consciousness module owns the 25k+ entry knowledge base. Access it via:

```
# Semantic search (needs embedding model warm):
mcp__archie__search_knowledge(query="your query here", limit=10)

# Text search (always works, even with embedding cold):
mcp__archie__search_knowledge(query="exact term", limit=10)

# Recall past context for a topic:
mcp__archie__recall_context(topic="module name or subject")

# Session briefing (needs embeddings — warns if cold):
mcp__archie__session_briefing(topic="what you're working on")
```

If embedding model is cold (0 results returned):
1. Warm via DHQ: `mcp__archie__delegate_task(capability='knowledge_analysis', reason='warm embedding model')`
2. Wait 30–60s for model_dispatch_worker to load the model
3. Retry search

Do NOT call the inference engine API directly to warm the model.
