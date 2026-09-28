---
description: Publish/deploy the static website — check deploy status, build the full-site zip lane-side, hand the push to Claude's hostinger MCP, then verify live and record it. Use when the user says "publish website", "deploy the site", "push kytranempowerment.com", "check deploy status", "why isn't my merge live yet".
---

Domain = first word of `$ARGUMENTS` (default `kytranempowerment.com`). Load
skill `deploy-website` and follow it. The lane's half:

1. **Status:** query `system_config` keys `website_deploy%` for the domain
   (`deploy_pending` = queued, not live).
2. **Prep (deploy_static only):** confirm the work is merged into main, then
   build the zip with the skill's python-stdlib recipe (canonical exclusions —
   especially `assets/portraits/*.png`; root `index.html` guard) into
   `platform_v2/_lane_ship/<domain>_<TS>.zip`. Skip thumb regen unless
   portraits changed (lane has no PIL — portrait changes go through host
   `scripts/publish_website.sh`).
3. **Push — lane-native (after opencode restart loads the MCP):** preflight with
   read-only `hosting_listWebsitesV1` (token+account check), then call MCP tool
   `hosting_deployStaticWebsite(domain="<domain>", archivePath="<zip path>",
   removeArchive=true)` — server runs in this lane, reads the zip directly,
   uploads + triggers deploy, account auto-resolves from the domain. **Only on
   the user's explicit deploy instruction** (full-site replace). Fallback if the
   MCP isn't loaded: *"Zip ready: `<path>` — ask Claude: deploy `<domain>` from
   archivePath `<path>`."* NEVER delegate `deploy_static` (only marks pending —
   task #3577); NEVER hand-roll Hostinger REST (wrong path 404s — KB #261679);
   only touch `hosting_deployStaticWebsite` + read-only `list*`/`get*` among the
   74 hosting tools.
4. **Verify + record:** after the push, `webfetch` a changed file from the live
   URL (30–120 s propagation; confirm NEW content, not just 200 — external
   vantage avoids the LAN false-negative, KB #269948). If live is updated but
   status still `deploy_pending`, run `mark_deploy_pushed` (the only writer of
   `deployed`).

`deploy_vps` domains (what-the-fact, civic/gov/legal/market) →
`delegate_task_to_fleet(capability="deploy_vps", …)`, one at a time. Full domain
map, zip recipe, and traps: skill `deploy-website`.
