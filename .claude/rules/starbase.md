---
globs: ["platform_v2/tools/department_hq/fleet_*.py", "platform_v2/tools/department_hq/templates/department_hq.html"]
---

# Fleet Management — Historical Notes (Superseded)

**`fleet.md` is authoritative for everything current** — route files, mesh map, DB tables,
node lifecycle, cross-node dispatch, model tiers, identity invariants. This file only holds
the handful of facts `fleet.md` doesn't restate. `frontend.md` owns the `sc-live`/`sc-static`
correction (do not re-add it here — it was previously duplicated in 3 files).

## History
Starbase Command + Starship + A.R.M.A.D.A. fully merged into Department HQ (2026-04-08).
Old Starbase/Starship modules are commented out in `module_registry.py`; old URLs redirect
via `app.py` `starship_compat_redirect`.

## Facts not in fleet.md
- Node RAM budget split: 80% agents, 5% swap, 15% host, 0% security (managed from hub)
- Status badge label set: ON DUTY / DEPLOYED / WORKING / BARRACKED / OFF DUTY
- Legacy StationOps UI (station-ops.js/css) still renders in the Fleet tab for backward
  compatibility — 10 station colors remain, but Department HQ is the source of truth for
  agent assignments; station panels are display-only.
- ComfyUI VRAM swap during fleet dispatch: `_vram_swap_for_comfyui(node_db_id)` /
  `_vram_restore_after_comfyui()` (general pattern also in `creative-studios.md`).
