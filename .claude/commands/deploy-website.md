# Deploy Website

Two deploy paths, by capability:

- **`deploy_static` (Hostinger shared hosting)** → Claude pushes DIRECTLY via the
  `mcp__hostinger-api__hosting_deployStaticWebsite` MCP tool. Do NOT delegate — the
  container can't reach the MCP tool (Anthropic infra), so delegating only marks
  `deploy_pending` and the live site never changes (task #3577).
- **`deploy_vps` (Docker products on the VPS)** → delegate to B.A.S.E. via
  `mcp__archie__delegate_task`; the container rsyncs the changed files + runs
  `docker compose up -d --build` over SSH, then verifies/retries/rolls back.

## CRITICAL — Hostinger has no REST deploy

**Hostinger Business Web Hosting (u982576611) has NO REST API deploy endpoint.**
`POST /api/hosting/v1/websites/{username}/deploy` → 404 (KB #261679). FTP is not used.
The ONLY working push is `mcp__hostinger-api__hosting_deployStaticWebsite`, which
**replaces `public_html` entirely** — always a FULL-site zip, never partial, one zip
per domain.

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
kytranempowerment.com:  source_path /mnt/archie_brain/website/kytranempowerment.com
                        verify_url  https://kytranempowerment.com/data/translations.json
creed-ai.org:           source_path /mnt/standalone/websites/creed-ai.org   # canonical repo (monorepo path is a symlink to this)
                        verify_url  https://creed-ai.org/data/translations.json
what-the-fact.com:      source_path /mnt/standalone/websites/what-the-fact.com  container wtf_consumer
                        verify_url  https://what-the-fact.com/static/data/translations.json
what-the-fact.tech:     source_path /mnt/standalone/websites/what-the-fact.com  container wtf_tech
                        verify_url  https://what-the-fact.tech/static/data/translations.json
civic.kytranempowerment.com:  source_path /mnt/standalone/kytran-civic-watch   container kytran_watch_api
                        changed_files ["static/data/translations.json"]  verify https://civic.kytranempowerment.com/data/translations.json
gov.kytranempowerment.com:    source_path /mnt/standalone/kytran-gov-watch     container kytran_gov_watch
                        changed_files ["static/data/translations.json"]  verify https://gov.kytranempowerment.com/static/data/translations.json
legal.kytranempowerment.com:  source_path /mnt/standalone/kytran-legal-watch   container kytran_legal_api
                        changed_files ["static/data/translations.json"]  verify https://legal.kytranempowerment.com/data/translations.json
market.kytranempowerment.com: source_path /mnt/standalone/kytran-market-watch  container kytran_market_api
                        changed_files ["static/data/translations.json"]  verify https://market.kytranempowerment.com/static/data/translations.json
```

`what-the-fact.tech` is on the Hostinger account too, but it serves a VPS product —
deploy it as `deploy_vps`, NOT static.

---

## Steps

### 1. Parse argument

If `$ARGUMENTS` is empty, list the Domain Map and ask which to deploy. Accept "all".
Validate the domain is in the map; if not, show the available domains.

### 2. Deploy

**`deploy_static` domains (kytranempowerment.com, creed-ai.org) — push DIRECTLY:**

1. Build the zip with `scripts/publish_website.sh` (preferred — it regenerates
   thumbs, syncs staging, applies the exclusion list and refuses an archive with
   no root `index.html`). Building by hand instead, use the SAME exclusions:
   ```bash
   TS=$(date +%Y%m%d_%H%M%S); cd <source_path>
   zip -rq /tmp/<domain>_${TS}.zip . \
     -x '.git/*' -x '.gitignore' -x 'assets/portraits/*.png'
   ```
   ⚠️ `assets/portraits/*.png` are SDXL ORIGINALS — the site serves the JPEG
   thumbs and references no portrait PNG at all. Including them added ~97 MB
   (77%) of never-requested bytes to a 126 MB full-site replace (2026-07-28).
2. Push (replaces `public_html` entirely):
   ```
   mcp__hostinger-api__hosting_deployStaticWebsite(domain="<domain>", archivePath="/tmp/<domain>_<TS>.zip", removeArchive=True)
   ```
   Expect `{"upload":{"status":"success"},"deploy":{"status":"success","data":{"message":"Request accepted"}}}`.
3. Record the push — **only after a success response**:
   ```bash
   docker exec archie_platform python3 -c "
   import sys; sys.path.insert(0,'/app')
   from services.deploy_service import mark_deploy_pushed
   print(mark_deploy_pushed('<domain>', artifact='<zip name>', file_count=<n>, bytes_pushed=<size>))"
   ```
   `mark_deploy_pushed` is the ONLY writer of status `deployed` — do NOT hand-write
   `success` into `system_config`. Nothing upstream can know bytes landed: the
   pipeline, the daily worker and the approval executor can only ever queue
   (`deploy_pending`). Skipping this step leaves the site reading "pending
   push" forever and makes the next run's change-detection re-send everything.
4. **Verify live** — fetch a changed file from `https://<domain>/...` and confirm the
   NEW content is served (Hostinger propagates in 30–120s). For widgets that fetch a
   hub API in the browser, verify from an EXTERNAL vantage (e.g. the outpost) — the
   hub LAN resolves `*.kytranempowerment.com` to a private IP, so Chrome's Private
   Network Access gives a false negative (KB #269948).

**`deploy_vps` domains — delegate (container rsyncs + rebuilds over SSH):**
```
mcp__archie__delegate_task(
    capability="deploy_vps",
    reason="Manual deploy via /deploy-website for {domain}",
    delegation_source="claude",
    args={domain, source_path, changed_files, verify_url, container_name},
)
```
Returns a task_id; B.A.S.E. (agent 139) runs snapshot → rsync → `docker compose up
-d --build` → verify → retry-once → rollback-on-double-failure, async.

For "all": push the `deploy_static` sites directly first, then the `deploy_vps`
sites one at a time (VPS has a single SSH connection).

### 3. Report

Print a table: `Domain | Capability | Result (✅/❌)`. For any `deploy_vps` failure,
note the error and that Repair Bay has a proposal queued.

---

## Check deploy status anytime

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT key, value FROM system_config WHERE key LIKE 'website_deploy%' ORDER BY key;"
```
`deploy_pending` = queued (a delegate `deploy_static` only ever marks this — push it
directly). `success` = last deploy worked. `failed` = last automated attempt broke.

## When to use

- After website HTML/JS/CSS/translations changes
- When `system_config` shows `deploy_pending`
- After approving portraits in Media Studio
- Whenever the user says "push the site", "deploy", "update website"

## What NOT to do

- Do NOT `POST /api/hosting/v1/websites/{username}/deploy` → 404
- Do NOT use FTP
- Do NOT deploy partial files — full-site zip only, always; one zip per domain
- Do NOT delegate `deploy_static` expecting a live push — it only marks pending
