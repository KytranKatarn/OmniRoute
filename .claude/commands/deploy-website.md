---
name: deploy-website
description: Deploy a website via the A.R.C.H.I.E. Autonomous Deploy Pipeline. B.A.S.E. handles zip, upload, verify, retry, and rollback. Covers Hostinger static sites and VPS Docker products.
allowed-tools: mcp__archie__delegate_task
argument: Domain name or "all". Omit to see available sites.
---

# Deploy Website via Autonomous Deploy Pipeline

All deploys go through `mcp__archie__delegate_task` — B.A.S.E. runs the full pipeline
(risk check → snapshot → execute → verify → retry → rollback + alert on failure).
Claude does not zip, upload, or SSH. One MCP call, platform does the rest.

## Domain Map

| Domain | Capability | Container / Account |
|--------|-----------|---------------------|
| kytranempowerment.com | deploy_static | Hostinger API |
| creed-ai.org | deploy_static | Hostinger API |
| what-the-fact.com | deploy_vps | wtf_consumer |
| what-the-fact.tech | deploy_vps | wtf_tech |
| civic.kytranempowerment.com | deploy_vps | kytran_watch_api |
| gov.kytranempowerment.com | deploy_vps | kytran_gov_watch |
| legal.kytranempowerment.com | deploy_vps | kytran_legal_api |
| market.kytranempowerment.com | deploy_vps | kytran_market_api |

## Deploy Context by Domain

```
kytranempowerment.com:
  source_path: /mnt/archie_brain/website/kytranempowerment.com
  changed_files: ["data/translations.json"]
  verify_url: https://kytranempowerment.com/data/translations.json

creed-ai.org:
  source_path: /mnt/standalone/websites/creed-ai.org
  changed_files: ["data/translations.json"]
  verify_url: https://creed-ai.org/data/translations.json

what-the-fact.com:
  source_path: /mnt/standalone/websites/what-the-fact.com
  changed_files: ["data/translations.json"]
  verify_url: https://what-the-fact.com/static/data/translations.json
  container_name: wtf_consumer

what-the-fact.tech:
  source_path: /mnt/standalone/websites/what-the-fact.com
  changed_files: ["data/translations.json"]
  verify_url: https://what-the-fact.tech/static/data/translations.json
  container_name: wtf_tech

civic.kytranempowerment.com:
  source_path: /mnt/standalone/kytran-civic-watch
  changed_files: ["static/data/translations.json"]
  verify_url: https://civic.kytranempowerment.com/data/translations.json
  container_name: kytran_watch_api

gov.kytranempowerment.com:
  source_path: /mnt/standalone/kytran-gov-watch
  changed_files: ["static/data/translations.json"]
  verify_url: https://gov.kytranempowerment.com/static/data/translations.json
  container_name: kytran_gov_watch

legal.kytranempowerment.com:
  source_path: /mnt/standalone/kytran-legal-watch
  changed_files: ["static/data/translations.json"]
  verify_url: https://legal.kytranempowerment.com/data/translations.json
  container_name: kytran_legal_api

market.kytranempowerment.com:
  source_path: /mnt/standalone/kytran-market-watch
  changed_files: ["static/data/translations.json"]
  verify_url: https://market.kytranempowerment.com/static/data/translations.json
  container_name: kytran_market_api
```

## Steps

### 1. Parse Argument

If `$ARGUMENTS` is empty, list the domain map above and ask which to deploy. Accept "all" to deploy all 8.

If `$ARGUMENTS` is a domain, validate it's in the domain map. If not, show available domains.

### 2. Deploy

**`deploy_static` domains (kytranempowerment.com, creed-ai.org) — deploy DIRECTLY. Do NOT delegate.**
The in-container pipeline CANNOT push to Hostinger — `hosting_deployStaticWebsite` runs on Anthropic infra, not inside the container. Delegating `deploy_static` only marks `deploy_pending`; the live site never changes, and the verify/retry on a push-that-never-happened used to wedge the delegate worker for 6 min (task #3577). So YOU do the push:

1. Zip the FULL site from its `source_path` (exclude `.git`):
   ```bash
   TS=$(date +%Y%m%d_%H%M%S); cd <source_path>
   zip -rq /tmp/<domain>_${TS}.zip . -x '.git/*' -x '.gitignore'
   ```
2. Push via MCP (replaces `public_html` entirely — always full-site zip):
   ```
   mcp__hostinger-api__hosting_deployStaticWebsite(domain="<domain>", archivePath="/tmp/<domain>_<TS>.zip", removeArchive=True)
   ```
   Expect `{"upload":{"status":"success"},"deploy":{"status":"success",...}}`.
3. Update `system_config` (Step 5 below) → `success` + run timestamp.
4. **Verify live**: fetch a changed file from `https://<domain>/...` and confirm the NEW content is served (not the old). For widgets that fetch a hub API, verify from an EXTERNAL vantage (e.g. outpost) — split-horizon DNS + Chrome Private Network Access give false negatives from the hub LAN (KB #269948).

**`deploy_vps` domains (civic/gov/legal/market watch, what-the-fact) — delegate (the container CAN rsync + `docker compose up --build` over SSH):**
```
mcp__archie__delegate_task(
    capability="deploy_vps",
    reason="Manual deploy triggered via /deploy-website for {domain}",
    delegation_source="claude",
    args={domain, source_path, changed_files, verify_url, container_name},
)
```

For "all": do the `deploy_static` sites directly first, then the `deploy_vps` sites one at a time (VPS has one SSH connection).

### 3. Report

Print a summary table:
```
Domain                          | Capability     | Result
kytranempowerment.com           | deploy_static  | ✅ success
creed-ai.org                    | deploy_static  | ✅ success
...
```

If any domain fails, say what the error was and that Repair Bay has a proposal queued.

## Notes

- B.A.S.E. (agent_id=139) owns all deploys — verify, retry, rollback are automatic
- Risky files (.py, Dockerfile, .sql) trigger a Telegram approval request instead of deploying
- Pre-deploy snapshot stored in knowledge_base for rollback
- deploy_static always deploys the FULL site (partial deploys break public_html)
- The pipeline runs async in the platform — the delegate_task call returns a task_id immediately
