---
name: deploy-website
description: Deploy kytranempowerment.com and/or creed-ai.org to Hostinger shared hosting. Use when portraits are approved, content changes, or system_config shows deploy_pending. This is the ONLY way to push to Hostinger — there is no REST API deploy endpoint for shared hosting. Always use this skill or the Repair Bay Ship tab.
---

# Deploy Website to Hostinger

## CRITICAL — Read Every Time

**Hostinger Business Web Hosting (u982576611) has NO REST API deploy endpoint.**
`POST /api/hosting/v1/websites/{username}/deploy` → 404 (confirmed 2026-05-01, KB #261679).
The ONLY working mechanism is `mcp__hostinger-api__hosting_deployStaticWebsite`.
Do not attempt raw HTTP calls. Do not attempt FTP. Use this skill.

---

## Sites on this account

| Domain | Source on disk |
|--------|----------------|
| kytranempowerment.com | `/mnt/archie_brain/website/kytranempowerment.com` |
| creed-ai.org | `/mnt/archie_brain/website/creed-ai.org` |

`what-the-fact.tech` is also on this Hostinger account but serves a different product (VPS container) — do NOT deploy it here.

---

## Step 1 — Check deploy status

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT key, value FROM system_config WHERE key LIKE 'website_deploy%' ORDER BY key;"
```

- `deploy_pending` = queued, needs your action
- `success` = last deploy worked
- `failed` = last automated attempt broke (automated pipeline uses wrong endpoint)

---

## Step 2 — Backfill missing portrait thumbnails

Portrait thumbs land in staging (`static/media/thumbs/`) when the container can't write to the repo (read-only mount pre-fix). After the docker-compose `:rw` fix (PR #448), approve_canonical writes directly. For any gaps, backfill manually:

```bash
STAGING=/mnt/archie_brain/platform_v2/static/media/thumbs
WEBSITE=/mnt/archie_brain/website/kytranempowerment.com/assets/portraits
CREED=/mnt/archie_brain/website/creed-ai.org/assets/portraits
for f in $STAGING/*.jpg; do
  stem=$(basename "$f")
  [ ! -f "$WEBSITE/$stem" ] && cp "$f" "$WEBSITE/$stem" && cp "$f" "$CREED/$stem" && echo "synced: $stem"
done
```

---

## Step 3 — Create zips (full site, no partial deploys)

```bash
TS=$(date +%Y%m%d_%H%M%S)
cd /mnt/archie_brain/website/kytranempowerment.com
zip -r /tmp/kytran_${TS}.zip . --exclude "*.git*" 2>/dev/null
cd /mnt/archie_brain/website/creed-ai.org
zip -r /tmp/creed_${TS}.zip . --exclude "*.git*" 2>/dev/null
ls -lh /tmp/kytran_${TS}.zip /tmp/creed_${TS}.zip
```

---

## Step 4 — Deploy via MCP tool

```
mcp__hostinger-api__hosting_deployStaticWebsite(
    domain="kytranempowerment.com",
    archivePath="/tmp/kytran_<TS>.zip",
    removeArchive=True
)

mcp__hostinger-api__hosting_deployStaticWebsite(
    domain="creed-ai.org",
    archivePath="/tmp/creed_<TS>.zip",
    removeArchive=True
)
```

Expected response: `{"upload":{"status":"success"},"deploy":{"status":"success","data":{"message":"Request accepted"}}}`

---

## Step 5 — Update system_config

```bash
docker exec archie_database psql -U archie -d archie -c "
  UPDATE system_config SET value='success', updated_at=NOW()
    WHERE key IN ('website_deploy_last_status_kytranempowerment.com','website_deploy_last_status_creed-ai.org');
  UPDATE system_config SET value='$(date -u +%Y-%m-%dT%H:%M:%S)', updated_at=NOW()
    WHERE key IN ('website_deploy_last_run_kytranempowerment.com','website_deploy_last_run_creed-ai.org');"
```

---

## Step 6 — Verify live

Check a recently deployed portrait:
`https://kytranempowerment.com/assets/portraits/<stem>.jpg`

Hostinger takes 30–120s to propagate. Refresh in browser after 1 min.

---

## When to use

- After approving portraits in Media Studio
- When system_config shows `deploy_pending`
- After website HTML/JS/CSS content changes
- When B.A.S.E. daily job marks deploys as pending
- Whenever user says "push the site", "deploy portraits", "update website"

## What NOT to do

- Do NOT call `POST /api/hosting/v1/websites/{username}/deploy` → 404
- Do NOT use FTP
- Do NOT deploy partial files — full site zip only, always
- Do NOT put both domains in one zip — separate zip per domain
