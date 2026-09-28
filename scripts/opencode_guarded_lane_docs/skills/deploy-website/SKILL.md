---
name: deploy-website
description: Publish/deploy the static website to Hostinger — check deploy status, build the full-site zip, push directly via the lane's hostinger-api MCP (hosting_deployStaticWebsite; Claude handoff as fallback), verify live, and record the deploy. Use when the user says "publish the website", "deploy the site", "push kytranempowerment.com", "check deploy status", "why isn't my merge live yet", or after website HTML/CSS/JS/translations changes merge.
---

# deploy-website — Phase 4 publish flow (opencode lane)

Port of `.claude/commands/deploy-website.md` + `scripts/publish_website.sh`,
verified 2026-09-23. **Since 2026-09-23 the lane pushes ITSELF** via its own
`hostinger-api` MCP (wired into `opencode.json`: local server
`/opencode-home/opt/node_modules/.bin/hostinger-hosting-mcp` — hosting group,
74 tools — with `APITOKEN` mirroring `/mnt/archie_brain/.mcp.json`; token
verified live via `hosting_listWebsitesV1`). Claude's identical MCP remains the
**fallback** (e.g. before an opencode restart loads the config). The lane still
has no `zip`/`rsync`/`curl` binaries — zip prep stays python-stdlib (§2).
Never print the APITOKEN; never hand-roll a Hostinger REST call (only the MCP's
path shape works — see traps). Merge ≠ deploy: a merged PR is NOT live until
this pipeline runs.

> Detail moved to `reference/lane-prep.md` — read it when the short version is not enough.

## 0. Status check first

```bash
docker exec archie_database psql -U archie -d archie -tAc \
  "SELECT key, value FROM system_config WHERE key LIKE 'website_deploy%' ORDER BY key;"
```
`deploy_pending` = queued, NOT live (this is what a delegate/static queue ever
sets). `success` = last push worked. Key names: `website_deploy_last_status_`,
`_last_push_`, `_last_artifact_`, `_last_run_` per domain. If status says
pending but the user asks "is it live?" — go to §3 verify; if live already shows
the new content, do the bookkeeping in §3, do not re-push.

## 1. Domain map (who does what)

| Domain | Capability | Source | Who preps zip | Who pushes |
|---|---|---|---|---|
| kytranempowerment.com | deploy_static | `/mnt/archie_brain/website/kytranempowerment.com` (standalone is a symlink to it) | **lane** | **lane** (`hostinger-api` MCP; fallback Claude) |
| creed-ai.org | deploy_static | `/mnt/standalone/websites/creed-ai.org` (out of lane edit scope) | Claude/host | Claude |
| what-the-fact.com / .tech | deploy_vps | standalone | — | delegate → B.A.S.E. |
| civic/gov/legal/market.* | deploy_vps | standalone | — | delegate → B.A.S.E. |

`what-the-fact.tech` is on the Hostinger account but is a VPS product — never
deploy it as static. Source edits outside `website/kytranempowerment.com` are
out of lane scope (deploying ≠ editing; record-only).

## 3. Verify + bookkeeping (after ANY push, whoever made it)

1. Wait 30–120 s (Hostinger propagation), then fetch a CHANGED file from the
   live site with `webfetch` (e.g.
   `https://kytranempowerment.com/data/translations.json` or the changed page)
   and confirm the NEW content/byte count — not just HTTP 200. `webfetch` runs
   from an external vantage, which is what you want: the hub LAN resolves
   `*.kytranempowerment.com` to a private IP and gives false negatives
   (KB #269948).
2. If live shows the new content but `website_deploy_last_status_<domain>` is
   still `deploy_pending`, record it (only `mark_deploy_pushed` may write
   `deployed` — never hand-write `success` into `system_config`):
   ```bash
   docker exec -i archie_platform python3 - <<'PY'
   import sys; sys.path.insert(0,'/app')
   from services.deploy_service import mark_deploy_pushed
   print(mark_deploy_pushed('kytranempowerment.com', artifact='<zip name>',
                            file_count=<n>, bytes_pushed=<size>))
   PY
   ```
3. Report: `Domain | zip | live-verified (✅/❌) | status recorded`.

## 4. Traps (paid lessons)

- **Hostinger REST by hand does NOT work** — Claude's manual
  `POST /api/hosting/v1/websites/{username}/deploy` → 404 (KB #261679); the MCP
  uses a different, working shape
  (`api/hosting/v1/accounts/{username}/websites/{domain}/deploy` + a separate
  upload-credentials leg). FTP is not used. Always go through the MCP tool.
- **Full-site zip only, always** — the push REPLACES `public_html`; a partial
  archive wipes the site. One zip per domain, root `index.html mandatory.
- **Never ship `assets/portraits/*.png`** — SDXL originals; the site serves JPEG
  thumbs and references zero portrait PNGs (97 MB = 77% of a 126 MB payload,
  2026-07-28). Excluded above; keep it that way.
- **Never delegate `deploy_static`** — it only marks `deploy_pending` (task #3577).
- **Lane tooling gaps are by design:** no `zip`/`rsync`/`curl` in this container,
  no PIL (image work only where mounts allow), host `gh` unauthed. Do not "fix"
  these by copying tokens around.
- **MCP tool discipline:** the `hostinger-api` server exposes all 74 hosting
  tools — including `hosting_deleteWebsiteV1`, `*deleteAccountDatabase*`,
  `*create*`/`*update*`. Touch ONLY `hosting_deployStaticWebsite` and read-only
  `list*`/`get*` tools; any create/update/delete needs an explicit owner
  instruction. Never print `APITOKEN` (it lives in `opencode.json`'s
  `environment` purely so the MCP child process can authenticate).
- The autocommit worker never sweeps HTML/CSS, but `translations.json` newline
  dirt churns — commit real translation changes properly before deploying.

## When to use

- After website HTML/JS/CSS/translations changes MERGE (merge ≠ deploy).
- When `system_config` shows `deploy_pending` (check §0 — it may already be live).
- After approving portraits in Media Studio (thumb-regen path).
- Whenever the user says "push the site", "deploy", "publish", "update website".
