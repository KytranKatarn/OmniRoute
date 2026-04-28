# Autonomous Deploy Pipeline — Design Spec

> **Date:** 2026-04-28
> **Status:** Approved
> **Project:** #292 — Autonomous Deploy Pipeline — Repair Bay + Department HQ Control
> **ADR:** #523

---

## Goal

Remove Claude as manual deploy executor. Wire all product deployments (Hostinger static sites, VPS Docker containers) through Department HQ dispatch so A.R.C.H.I.E.'s team owns the full pipeline: translate → bundle → deploy → verify — without a human-in-the-loop for routine deploys.

---

## Scope (Part A — Deploy Actions)

This spec covers the deploy action pipeline only. Part B (All Hands parallel dispatch) is a separate spec.

---

## Architecture

**Pattern:** Two new Department HQ capabilities (`deploy_static`, `deploy_vps`) owned by **Operations & Infrastructure** (B.A.S.E. as director). All deploy work routes through `dispatch()`, inheriting: C.R.E.E.D. welfare gate, cost tracking, `unified_tasks` history, Telegram escalation.

A new `platform_v2/services/deploy_service.py` implements the execution logic. Repair Bay and the translation pipeline become thin callers — they dispatch, B.A.S.E. executes.

---

## Capabilities

| Capability | Owner department | B.A.S.E. skill level | Use |
|------------|-----------------|---------------------|-----|
| `deploy_static` | Operations & Infrastructure | Lv5 | Hostinger zip deploy for static sites |
| `deploy_vps` | Operations & Infrastructure | Lv5 | VPS SSH rsync + docker compose rebuild |

Add both to `CAPABILITY_DEPARTMENT_MAP` in `department_coordinator.py` and `department_dispatcher.py`.
Seed both skills on B.A.S.E. (agent_id=139, Operations & Infrastructure).

### Dispatch shape

```python
dispatch(
    capability='deploy_static',   # or 'deploy_vps'
    context={
        "domain": "kytranempowerment.com",
        "source_path": "/mnt/archie_brain/website/kytranempowerment.com",
        "changed_files": ["data/translations.json"],  # determines risk level
        "reason": "R.O.S.E.T.T.A. translation bundle complete",
    }
)
```

---

## Execution Pipeline (`deploy_service.py`)

Every deploy runs this 5-step pipeline:

### Step 1 — Risk classification

Inspect `changed_files`. If **all** files are `.json`, `.js`, `.css`, or `.html` → **auto-execute**. If any file is `.py`, `Dockerfile`, `docker-compose.yml`, or a migration → **Telegram approval required** (same `request_approval()` pattern as cloud escalation, `tier=2`).

### Step 2 — Pre-deploy backup (Backup Manager)

Before touching the live site, snapshot current state:
- `deploy_static`: fetch current `translations.json` from the live URL and store via Backup Manager with tags `['deploy-snapshot', 'pre-deploy', domain]`
- `deploy_vps`: Backup Manager file snapshot of the VPS static dir via SSH

On failure → restore from this snapshot.

### Step 3 — Execute

**`deploy_static`:**
1. `zip -r /tmp/<domain>_deploy_<ts>.zip <source_path>` (exclude `.git/`, `*.bak*`)
2. Hostinger `deployStaticWebsite(domain, archivePath)` — **full zip, never partial**
3. Clean up zip after deploy

**`deploy_vps`:**
1. `rsync -az --mkpath <changed_files> kytran@76.13.107.109:<target_dir>/` via `REPAIR_BAY_VPS_KEY`
2. `ssh kytran@76.13.107.109 "cd <compose_dir> && docker compose up -d --build --no-deps <service>"`

**VPS service name map** (from KB #261506):

| Container | Compose dir | Service name | Static URL path |
|-----------|-------------|-------------|-----------------|
| kytran_gov_watch | `/opt/archie-products/gov-watch/` | `kytran-gov-watch` | `/static/data/` |
| kytran_watch_api | `/opt/archie-products/civic-watch/` | `watch-api` | `/data/` ← root |
| kytran_legal_api | `/opt/archie-products/legal-watch/` | `legal-api` | `/data/` ← root |
| kytran_market_api | `/opt/kytran-market-watch/` | (default) | `/static/data/` |
| wtf_consumer | `/opt/archie-products/what-the-fact/` | `wtf-consumer` | `/static/data/` |
| wtf_tech | `/opt/archie-products/what-the-fact/` | `wtf-tech` | `/static/data/` |

### Step 4 — Verify

Wait 8 seconds after deploy, then:
- `GET` target URL → must return HTTP 200
- For translation deploys: `GET <translations_url>` → parse JSON → assert 0 Mock values, 0 empty strings

Pass → log success to `unified_tasks.work_notes`, update `translation_domain_registry.last_audit_at`.

### Step 5 — Failure handling

**On first failure:** wait 120 seconds, retry Step 3 once.

**On second failure:**
1. Backup Manager restore from Step 2 snapshot
2. Telegram alert to Kytran with error detail
3. Create Repair Bay failed proposal (`status='proposed'`, `category='deploy_failure'`)
4. Mark `unified_tasks` row as `blocked` with error

---

## Integration Points

### 1. Translation pipeline (primary trigger)

In `translation_scanners/orchestrator.py`, after `_export_bundle(label, bundle_path)` succeeds:

```python
# Auto-dispatch deploy for external sites
if label in ("website_kytranempowerment", "website_creed"):
    from tools.department_hq.services.department_dispatcher import dispatch
    dispatch(
        capability='deploy_static',
        context={
            "domain": DOMAIN_BY_LABEL[label],
            "source_path": SOURCEPATH_BY_LABEL[label],
            "changed_files": ["data/translations.json"],
            "reason": f"Translation bundle export complete for {label}",
        },
        module_id="translation_scanner",
    )
```

`DOMAIN_BY_LABEL` and `SOURCEPATH_BY_LABEL` are small dicts added alongside the existing `EXTERNAL_SCAN_SOURCES` list.

### 2. Repair Bay deploy routes

`repair_bay/deploy_routes.py` `/api/deploy/execute` becomes a thin wrapper:

```python
# Instead of executing directly:
result = dispatch(capability='deploy_static', context=payload)
return jsonify(result)
```

Repair Bay stays the UI/proposal layer. Department HQ owns execution.

### 3. P.R.O.B.E. (future, Phase 2)

After a visual scan confirms 0 gaps, P.R.O.B.E. dispatches a final deploy to close the loop:
`audit → translate → deploy → verify → done`

---

## SSH / Credentials

| Credential | .env key | Value |
|-----------|---------|-------|
| VPS SSH key path | `REPAIR_BAY_VPS_KEY` | `/home/kytran/.ssh/repair_bay_deploy` |
| VPS host | `REPAIR_BAY_VPS_HOST` | `kytran@76.13.107.109` |

Key is already installed on VPS (Task #2389 complete, 2026-04-28).

---

## Files to Create / Modify

| File | Action | What |
|------|--------|------|
| `platform_v2/services/deploy_service.py` | Create | Full deploy pipeline: risk check, backup, execute, verify, retry, rollback |
| `platform_v2/tools/department_hq/services/department_coordinator.py` | Modify | Add `deploy_static`, `deploy_vps` to `CAPABILITY_DEPARTMENT_MAP` |
| `platform_v2/tools/department_hq/services/department_dispatcher.py` | Modify | Add same 2 capabilities |
| `platform_v2/tools/consciousness/translation_scanners/orchestrator.py` | Modify | Dispatch `deploy_static` after `_export_bundle()` |
| `platform_v2/tools/repair_bay/deploy_routes.py` | Modify | Wrap `/api/deploy/execute` to call `dispatch()` |
| `platform_v2/database/migrations/173_deploy_capabilities.sql` | Create | Seed `deploy_static` + `deploy_vps` skills on B.A.S.E. |

---

## Success Criteria

- R.O.S.E.T.T.A. finishes translating → B.A.S.E. deploys → site live — zero Claude involvement
- All `.json/.js/.css/.html` deploys auto-execute without Telegram prompt
- Any `.py/Dockerfile` change requires Telegram approval before deploy
- Pre-deploy backup exists in Backup Manager before every deploy
- On failure: retry once → restore → alert → Repair Bay proposal
- VPS key auth works via `REPAIR_BAY_VPS_KEY` (no password)
- All deploy work visible in `unified_tasks` with agent attribution
