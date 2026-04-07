---
name: deploy-website
description: Deploy kytranempowerment.com static website to Hostinger hosting
user_invocable: true
---

# Deploy Website to Hostinger

Deploy the static website at `website/kytranempowerment.com/` to Hostinger shared hosting.

## Pre-Deploy Checklist

1. **Verify changes are committed** — `git status` should show no modified files under `website/kytranempowerment.com/`
2. **Review what changed** — `git log --oneline -5 -- website/kytranempowerment.com/` to see recent changes
3. **Quick sanity check** — open 1-2 modified HTML files and verify they look correct

## Deploy Steps

1. Create archive from the website directory:
   ```bash
   cd /mnt/archie_brain/website/kytranempowerment.com && tar -czf /tmp/kytranempowerment_deploy.tar.gz --exclude='./_fix_nav_mobile.py' --exclude='./.git' .
   ```

2. Deploy via Hostinger MCP tool:
   ```
   mcp__hostinger-api__hosting_deployStaticWebsite(
     domain: "kytranempowerment.com",
     archivePath: "/tmp/kytranempowerment_deploy.tar.gz",
     removeArchive: true
   )
   ```

3. **Verify deployment** — wait 1-2 minutes, then check the live site via browser or curl:
   ```bash
   curl -sI https://kytranempowerment.com | head -5
   ```

## Post-Deploy

- Confirm HTTP 200 response
- Spot-check 2-3 pages that were changed
- Update session handoff with deployment confirmation

## Notes

- Archive is ~14MB for the full site
- Hostinger extracts the archive server-side
- DNS points root domain to Hostinger CDN (cdn.hstgr.net)
- Subdomains (market, civic, legal, gov, thenews) are on VPS — NOT affected by this deploy
- `creed-ai.org` is separate Hostinger hosting — deploy separately if needed
