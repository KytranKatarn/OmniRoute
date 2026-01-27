# Storage Tab Interactive Disk Management — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current Storage tab (static partition tables) with an interactive visual disk management interface featuring treemap visualization, donut charts, action panel, and a `storage_mounts` DB table as the bridge for the future Docker multi-stack feature.

**Architecture:** The Storage tab reads disk data from `host_monitor_data.json` (collected by `host_monitor.py` on the host). The new UI renders a treemap of drives/partitions with click-to-select, a right-side action panel for operations, and supplementary donut charts. A new `storage_mounts` DB table tracks managed partitions for cross-tab integration. Safe operations use a confirm modal; destructive operations use a re-auth modal requiring password entry.

**Tech Stack:** Python/Flask (routes.py), PostgreSQL (storage_mounts table), Vanilla JS + inline SVG treemap + Chart.js donuts, existing A.R.C.H.I.E. CSS variables.

**Note on innerHTML:** This codebase renders all dynamic content via innerHTML following the existing pattern throughout `system_operations.html`. All data originates from the host monitor (trusted) or the platform API (authenticated). This is consistent with how `renderPartitions()`, `renderDocker()`, `renderHostDisks()`, `renderNetwork()`, and all other rendering functions work in this template.

---

## Scope and Phasing

This plan implements the Storage tab in **3 phases** across **12 tasks**:

- **Phase 1 (Tasks 1-4):** Database table, enhanced host_monitor data, new API endpoints, re-auth endpoint
- **Phase 2 (Tasks 5-8):** Storage tab HTML/CSS rewrite (treemap, donut charts, action panel, modals)
- **Phase 3 (Tasks 9-12):** Storage tab JS (rendering, interactions, API calls, Dashboard integration)

**Not in scope (deferred to Docker/Network designs):** Docker-Storage bridge UI, stack volume allocation, bandwidth monitoring.

---

## Task 1: Create `storage_mounts` Database Table

**Files:**
- Create: `/mnt/archie_brain/scripts/create_storage_mounts_table.sql`

**Step 1: Write the SQL migration**

```sql
-- Storage Mounts table: tracks managed partitions for cross-tab integration
CREATE TABLE IF NOT EXISTS storage_mounts (
    id SERIAL PRIMARY KEY,
    device VARCHAR(100) NOT NULL,
    mount_point VARCHAR(500),
    filesystem VARCHAR(50),
    label VARCHAR(100),
    capacity_gb DECIMAL(10,2),
    drive_model VARCHAR(200),
    is_managed BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(device)
);

-- Index for Docker bridge lookups
CREATE INDEX IF NOT EXISTS idx_storage_mounts_managed ON storage_mounts(is_managed) WHERE is_managed = TRUE;

COMMENT ON TABLE storage_mounts IS 'Managed storage partitions - bridge between Storage and Docker tabs';
```

**Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/scripts/create_storage_mounts_table.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, `COMMENT`

**Step 3: Commit**

```bash
git add scripts/create_storage_mounts_table.sql
git commit -m "feat(storage): add storage_mounts database table for managed partitions"
```

---

## Task 2: Enhance host_monitor.py Storage Data Collection

**Files:**
- Modify: `/mnt/archie_brain/scripts/host_monitor.py`

**What to add:** The existing `get_disk_layout()` collects lsblk data. Enhance with:
1. `blkid` output for UUID and label per partition
2. SMART health status via `smartctl`
3. Disk I/O rates from `/proc/diskstats`
4. Merge this enrichment data into the existing disk layout output

**Step 1: Add `get_blkid_info()` helper function**

Add after `_add_usage_stats()` function (after line 411).

**Step 2: Add `get_disk_io_rates()` function**

Reads `/proc/diskstats` for reads_completed, sectors_read, writes_completed, sectors_written, io_in_progress per device name.

**Step 3: Add `get_smart_health()` function**

Runs `smartctl -H /dev/{name}` for each disk device. Returns dict mapping name to "healthy", "failing", "unknown", or "unavailable".

**Step 4: Enhance `get_disk_layout()` to merge enrichment data**

Before the `return disks` statement at end of function, add calls to:
- `get_blkid_info()` — merge `uuid` and `label` into each partition and child
- `get_smart_health()` — add `smart_health` field to each disk
- `get_disk_io_rates()` — add `io` field to each disk

**Step 5: Test on host**

```bash
cd /mnt/archie_brain && python3 scripts/host_monitor.py
```

Verify JSON output includes `uuid`, `label`, `smart_health`, and `io` fields.

**Step 6: Commit**

```bash
git add scripts/host_monitor.py
git commit -m "feat(storage): enhance host monitor with blkid, SMART, and disk I/O data"
```

---

## Task 3: Add Storage API Endpoints to routes.py

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/system_operations/routes.py`

**Step 1: Add storage endpoints before the AUDIT LOG section (before line 965)**

Add these endpoints with existing `@login_required` + `@admin_required` decorator pattern:

1. **`GET /api/storage/drives`** — Returns host monitor disk data with LVM VG free space merged. This is the primary data source for the treemap.

2. **`GET /api/storage/mounts`** — Returns managed storage mounts from `storage_mounts` database table (for Docker bridge).

3. **`POST /api/storage/mounts`** — Registers a new managed storage mount. Uses `ON CONFLICT (device) DO UPDATE` for upsert. Calls `audit_log()`.

4. **`GET /api/storage/browse`** — Browse a directory listing. Security: only allow paths under `/mnt/`, `/home/`, `/var/`, `/opt/`, `/srv/`, `/tmp/`. Returns entries with name, is_dir, size, modified. Limited to 200 entries.

All endpoints follow the existing JSON response pattern: `{'success': True, 'data': ...}`.

**Step 2: Commit**

```bash
git add platform_v2/tools/system_operations/routes.py
git commit -m "feat(storage): add storage drives, mounts, and browse API endpoints"
```

---

## Task 4: Add Re-Authentication Endpoint

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/system_operations/routes.py`

**Step 1: Add `POST /api/auth/verify` endpoint**

- Requires `password` in JSON body
- Uses `werkzeug.security.check_password_hash` to verify against `users.password_hash`
- On success: stores `reauth_timestamp` in Flask session (5 minute validity)
- On failure: returns 401, logs via `audit_log()`
- On success: returns 200, logs via `audit_log()`

**Step 2: Add `require_reauth()` helper function**

After `record_metric()`: checks `session['reauth_timestamp']` is within 300 seconds. Returns None if OK, or JSON error with `requires_reauth: true` if expired.

**Step 3: Commit**

```bash
git add platform_v2/tools/system_operations/routes.py
git commit -m "feat(storage): add re-authentication endpoint and helper for destructive ops"
```

---

## Task 5: Rewrite Storage Tab HTML Structure

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**What:** Replace the entire `<div id="tab-storage">` content (lines 1208-1295) with new layout:

1. **Storage Overview Bar** — Top bar with Total/Used/Free/Drives/Health stats + Refresh button
2. **Main Layout** — CSS Grid: left visual area (treemap + charts + LVM + RAID) + right action panel
3. **Treemap Panel** — `<div id="storage-treemap">` container for JS rendering
4. **Charts Row** — Overall donut canvas + per-drive charts container
5. **LVM Configuration** — Same 3-column grid as before (VGs, LVs, PVs)
6. **RAID Status** — Same as before
7. **Action Panel** — Right sidebar with header, body, close button. Starts hidden.

Preserve existing element IDs: `lvm-vgs`, `lvm-lvs`, `lvm-pvs`, `lvm-none`, `raid-status`, `lvm-panel`.

**Step 1: Replace the tab-storage div content**

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): rewrite storage tab HTML with treemap layout and action panel"
```

---

## Task 6: Add Storage Tab CSS Styles

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**What:** Add CSS in the `<style>` block after `.host-badge` styles (after line ~591), before Docker styles.

New CSS classes needed:
- `.storage-overview-bar`, `.storage-overview-stat`, `.storage-overview-label`, `.storage-overview-value`
- `.storage-main-layout` (grid: 1fr 340px), `.storage-main-layout.panel-closed` (1fr only)
- `.storage-visual-area`
- `.treemap-drive`, `.treemap-drive-header`, `.treemap-drive-name`, `.treemap-drive-model`, `.treemap-drive-size`, `.treemap-drive-health` (with .healthy/.failing/.unknown variants)
- `.treemap-partitions` (flexbox row, 60px height)
- `.treemap-partition` (flex item, rounded, cursor pointer, transition), with variants: `.mounted` (green gradient), `.unmounted` (striped grey), `.lvm-free` (dashed cyan), `.unallocated` (dashed purple), `.new-drive` (pulsing animation), `.selected` (accent border + glow)
- `.treemap-partition-label`, `.treemap-partition-size`, `.treemap-partition-usage` (bottom usage bar)
- `.storage-charts-row` (grid: 250px 1fr)
- `.storage-action-panel` (sticky, right side), `.storage-action-panel.hidden`, `.storage-action-header`, `.storage-action-body`
- `.action-info-grid`, `.action-info-item`, `.action-info-label`, `.action-info-value`
- `.action-buttons`, `.action-btn-storage`, `.action-btn-storage.destructive`
- Responsive: `@media (max-width: 1100px)` collapses to single column

**Step 1: Add the CSS**

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add CSS styles for treemap, charts, and action panel"
```

---

## Task 7: Add Re-Auth Modal HTML

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**What:** Add modal HTML after `lvmExtendModal` and before `<!-- Toast Container -->`.

Structure: `.modal-overlay#reauthModal` > `.modal.modal-sm` with:
- Header: shield icon + "Re-Authentication Required" in orange
- Body: operation message, password input with Enter keydown, error div (hidden by default)
- Footer: Cancel (btn-ghost) + "Verify & Continue" (btn-danger)

**Step 1: Add the modal HTML**

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add re-authentication modal for destructive operations"
```

---

## Task 8: Add Storage JavaScript — Data Loading & Treemap Rendering

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**Step 1: Add state variables** after existing state block (after `hostStorageLoaded`):
- `storageData`, `selectedPartition`, `storageOverallChart`, `reauthCallback`

**Step 2: Add `loadStorageData()`** — fetches `/api/storage/drives`, stores data, calls treemap/overview/charts/LVM renderers

**Step 3: Add `renderStorageOverview(disks)`** — calculates total/used/free across all disks, updates the overview bar elements. Add helper `formatSize(gb)`.

**Step 4: Add `renderStorageTreemap(disks, lvm)`** — builds HTML for each drive:
- Drive header: device name, model, SMART health badge, size
- Partition row: proportional flex blocks, colored by state
- For LVM partitions: show children + VG free space block
- For unmounted: striped pattern, lower opacity
- For unallocated: dashed border, purple
- Each block has onclick calling `selectPartition()`

Add helper `getUsageColor(pct)` returning CSS var for red/orange/green.

**Step 5: Update `loadHostData()`** — after existing `renderHostServices()` call, add calls to `renderStorageTreemap()`, `renderStorageOverview()`, `renderStorageCharts()` if `json.data.disks` exists.

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add treemap rendering and storage data loading JS"
```

---

## Task 9: Add Storage JavaScript — Charts

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**Step 1: Add `renderStorageCharts(disks)`**

- Overall donut: sums used/free/unmounted across all disks, renders on `#storageOverallChart` canvas
- Per-drive donuts: generates canvas elements in `#storage-per-drive-charts`, renders individual donuts
- Uses existing Chart.js (already loaded), same styling as CPU/Memory charts
- Colors: accent (used), green (free), #444 (unmounted)
- Destroys previous chart instance before creating new one

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add donut chart rendering for overall and per-drive usage"
```

---

## Task 10: Add Storage JavaScript — Action Panel

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**Step 1: Add partition selection and panel rendering functions**

- `selectPartition(element, diskName, devicePath, partType)` — deselects previous, selects new, shows action panel, routes to appropriate renderer
- `closeActionPanel()` — hides panel, deselects
- `renderPartitionActions(disk, part)` — shows info grid (device, filesystem, size, mount, UUID), usage bar, type badges, action buttons:
  - Mounted: Browse Files, Extend (if LVM + free), Shrink (re-auth), Unmount (re-auth)
  - Unmounted: Mount, Format (re-auth)
- `renderLvmFreeActions(disk, vgRef)` — Create New LV, Extend Existing LV
- `renderUnallocatedActions(disk)` — Create New Partition
- `renderUninitializedActions(disk)` — Launch Setup Wizard (re-auth)
- `browsePartition(mountpoint)` — fetches `/api/storage/browse`, renders file table with folder navigation

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add action panel rendering for partition details and actions"
```

---

## Task 11: Add Re-Auth JavaScript & Toast Functions

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**Step 1: Add re-auth functions**

- `requestReauth(operationName, callback)` — stores callback, shows modal, focuses password input
- `closeReauthModal()` — hides modal, clears password
- `submitReauth()` — POSTs to `/api/auth/verify`, on success closes modal and calls callback, on failure shows error

**Step 2: Add `showToast(message, type)` if not already present**

Creates temporary notification elements in `#toastContainer` with auto-dismiss after 4 seconds.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): add re-auth modal JS and toast notification support"
```

---

## Task 12: Update Initialization & Dashboard Integration

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html`

**Step 1: Update `refreshAll()`** — add `loadStorageData()` to the Promise.allSettled array

**Step 2: Update `updateDashboard()`** — after disk section, add per-drive mini summary:
- For each host disk: show name, progress bar, used/total text
- Renders into `#dashboard-drive-summary` div

**Step 3: Add `#dashboard-drive-summary` div** in Dashboard tab HTML inside the disk stat card

**Step 4: Initialize action panel as hidden** in DOMContentLoaded handler

**Step 5: Restart container and test**

```bash
docker compose restart archie_platform
```

Verify:
- Storage tab: overview bar, treemap, donut charts, LVM tables, action panel on click
- Dashboard tab: per-drive progress bars
- Re-auth modal: appears for destructive actions, password verification works

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/system_operations.html
git commit -m "feat(storage): complete storage tab with dashboard integration and init"
```

---

## Implementation Summary

| Task | Description | Files | Phase |
|------|-------------|-------|-------|
| 1 | Database table `storage_mounts` | SQL script | Phase 1 |
| 2 | Enhanced host_monitor (blkid, SMART, I/O) | host_monitor.py | Phase 1 |
| 3 | Storage API endpoints (drives, mounts, browse) | routes.py | Phase 1 |
| 4 | Re-auth endpoint + helper | routes.py | Phase 1 |
| 5 | Storage tab HTML rewrite | system_operations.html | Phase 2 |
| 6 | Storage CSS (treemap, charts, action panel) | system_operations.html | Phase 2 |
| 7 | Re-auth modal HTML | system_operations.html | Phase 2 |
| 8 | JS: Data loading + treemap rendering | system_operations.html | Phase 3 |
| 9 | JS: Chart.js donut charts | system_operations.html | Phase 3 |
| 10 | JS: Action panel interactions | system_operations.html | Phase 3 |
| 11 | JS: Re-auth modal + toasts | system_operations.html | Phase 3 |
| 12 | JS: Init, refreshAll, Dashboard integration | system_operations.html | Phase 3 |

**Total commits:** 12 (one per task)

**Dependencies:**
- Tasks 1-4 can proceed in parallel (Phase 1 backend)
- Tasks 5-7 (HTML/CSS) should go before Tasks 8-12 (JS)
- Task 12 depends on all previous tasks
- Container restart needed after Phase 2/3 changes for Flask template cache refresh
