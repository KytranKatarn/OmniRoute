---
name: deploy-website
description: Deploy a static website to Hostinger shared hosting. Tries API first, falls back to FTP.
allowed-tools: Bash, mcp__hostinger-api__hosting_deployStaticWebsite
argument: Domain name (e.g., kytranempowerment.com). Omit to see available sites.
---

# Deploy Website to Hostinger

## Domain Map

| Domain | Local Source |
|--------|-------------|
| kytranempowerment.com | /mnt/standalone/websites/kytranempowerment.com/ |
| creed-ai.org | /mnt/standalone/websites/creed-ai.org/ |
| what-the-fact.com | /mnt/standalone/websites/what-the-fact.com/ |
| what-the-fact.tech | /mnt/standalone/websites/what-the-fact.com/ |

## Steps

### 1. Parse Argument

If `$ARGUMENTS` is empty, list the available domains above and ask which to deploy. Accept "all" to deploy all 4.

If `$ARGUMENTS` is a domain, validate it's in the domain map. If not, show available domains.

### 2. Resolve Source Path

Map the domain to its local source path from the table above.

### 3. Try Hostinger API First

Create a zip archive:
```bash
cd SOURCE_PATH && zip -r /tmp/DOMAIN_deploy.zip . -x ".git/*" ".github/*" "CONTRIBUTING.md" "SECURITY.md" "CODE_OF_CONDUCT.md" "CHANGELOG.md" "LICENSE" "README.md" ".gitignore"
```

Call `mcp__hostinger-api__hosting_deployStaticWebsite` with the domain and archive path.

If the response shows `deploy.status: "success"` — done. Clean up the zip and report success.

### 4. FTP Fallback (if API fails)

If the API returns an error (typically 500 on extract), fall back to FTP:

```bash
lftp -u u982576611,"$HOSTINGER_FTP_PASS" ftp://45.84.207.23 -e "set ssl:verify-certificate no; mirror -R --exclude .git/ --exclude .github/ --exclude CONTRIBUTING.md --exclude SECURITY.md --exclude CODE_OF_CONDUCT.md --exclude CHANGELOG.md --exclude LICENSE --exclude README.md --exclude .gitignore SOURCE_PATH domains/DOMAIN/public_html/; quit"
```

If `HOSTINGER_FTP_PASS` env var is not set, tell the user:
> "FTP password not found. Set it with: `export HOSTINGER_FTP_PASS='your-password'`"

### 5. Verify

Check the site returns HTTP 200:
```bash
curl -s -o /dev/null -w "%{http_code}" https://DOMAIN/
```

### 6. Report

Print: domain, method used (API or FTP), HTTP status, success/failure.

## Notes

- FTP uses `lftp` mirror which only syncs changed files (fast incremental deploys)
- Hostinger API upload works but extract has been broken since 2026-04-14 (returns 500)
- All 4 domains share the same Hostinger account (u982576611)
- The zip is cleaned up after deploy regardless of method
