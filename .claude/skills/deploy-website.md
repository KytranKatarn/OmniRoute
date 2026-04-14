---
name: deploy-website
description: This skill should be used when the user asks to "deploy website", "push to Hostinger", "deploy creed-ai.org", "deploy kytranempowerment.com", "update live site", or mentions deploying static websites to Hostinger hosting. Handles both kytranempowerment.com and creed-ai.org with retry logic and verification.
user_invocable: true
---

# Deploy Static Websites to Hostinger

Deploy static websites to Hostinger shared hosting. Supports two sites:

| Site | Source | Domain | Archive Size |
|------|--------|--------|-------------|
| Kytran Empowerment | `website/kytranempowerment.com/` | kytranempowerment.com | ~110MB |
| C.R.E.E.D. Institute | `website/creed-ai.org/` | creed-ai.org | ~200KB |

## Usage

Invoke with optional site argument:
- `/deploy-website` — deploy both sites
- `/deploy-website kytran` — deploy kytranempowerment.com only
- `/deploy-website creed` — deploy creed-ai.org only

## Pre-Deploy Checklist

1. **Verify changes committed** — `git status -- website/` should show no unexpected modifications
2. **Review changes** — `git log --oneline -5 -- website/kytranempowerment.com/ website/creed-ai.org/`
3. **Quick sanity check** — read 1-2 modified HTML files to verify correctness

## Deploy Process (Per Site)

### Step 1: Create Archive

Use zip format (more reliable with Hostinger):

```bash
# For kytranempowerment.com:
cd /mnt/archie_brain/website/kytranempowerment.com && \
  zip -r /tmp/kytranempowerment_deploy_$(date +%Y%m%d_%H%M%S).zip . \
  -x "*.git*" -x "./_fix_nav_mobile.py"

# For creed-ai.org:
cd /mnt/archie_brain/website/creed-ai.org && \
  zip -r /tmp/creed-ai_deploy_$(date +%Y%m%d_%H%M%S).zip . \
  -x "*.git*"
```

If `zip` is not installed, use tar.gz:
```bash
tar czf /tmp/site_deploy.tar.gz --exclude='.git*' -C /path/to/site .
```

### Step 2: Deploy via Hostinger API

```
mcp__hostinger-api__hosting_deployStaticWebsite(
  domain: "DOMAIN",
  archivePath: "/tmp/ARCHIVE_FILE",
  removeArchive: false  # keep for retry
)
```

### Step 3: Retry Logic

If deploy returns status 500 (Hostinger server error):

1. **Wait 30 seconds**, then retry the same deploy call (archive is still on disk)
2. If second attempt fails, **wait 60 seconds** and retry once more
3. After 3 failures, the archive was uploaded to Hostinger but extraction failed server-side

**Fallback when API fails:**
- Inform user: "Hostinger deploy API returned 500. The archive was uploaded successfully."
- Instruct user to manually extract via hPanel:
  1. Log into Hostinger hPanel
  2. File Manager → navigate to public_html for the domain
  3. Find the uploaded archive → right-click → Extract
- Create an ARCHIE task to retry deployment next session

### Step 4: Verify Deployment

Wait 60 seconds after successful deploy, then verify:

```bash
# Check HTTP response
curl -sI https://DOMAIN | head -5

# Check specific changed page content (pick a page that was modified)
curl -s https://DOMAIN/PAGE.html | grep "EXPECTED_CONTENT"
```

For creed-ai.org, also verify the governance page fetches live data:
```bash
curl -s https://creed-ai.org/governance.html | grep "creed.kytranempowerment.com/api"
```

## Post-Deploy

- Confirm HTTP 200 on both sites
- Spot-check 2-3 pages that were modified
- Log deployment via `mcp__archie__log_decision` if significant changes
- Update session handoff with deployment confirmation

## Important Notes

- **Deploy one site at a time** — do NOT parallel deploy, Hostinger may rate limit
- DNS: root domains point to Hostinger CDN (cdn.hstgr.net)
- VPS subdomains (market, civic, legal, gov, thenews) are NOT affected by Hostinger deploys
- creed.kytranempowerment.com runs on Docker (hub) — NOT a Hostinger deploy
- Always keep archive on disk until verification passes (set removeArchive: false)
- Clean up archives after verification: `rm /tmp/*_deploy_*.{zip,tar.gz}`
