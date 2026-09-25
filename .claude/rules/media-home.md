---
globs: ["platform_v2/tools/media_hub/**"]
---

# Media Home — RETIRED, see media-hub.md

This file described an in-platform `/tools/media-hub` blueprint (`media_hub_bp`,
`tools/media_hub/routes.py`, `media_hub_requests`/`media_hub_settings` tables) that no
longer exists — confirmed 2026-09-25: `platform_v2/tools/media_hub/` is absent from the
filesystem and `media_hub_bp` is not registered in `module_registry.py`. The module was
consolidated into a standalone (Project #384, PRs #2100/#2101, 2026-07-08); `/tools/media-hub`
is now a pure `external_url` launch tile pointing at `media.kytranempowerment.com`.

**Current state, tables, routes, and gotchas live in `media-hub.md`** — read that file.
