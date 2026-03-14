# Media Studio Layer 10: Media Analytics — Design Spec

## Overview

Add a full analytics dashboard to Media Studio. Users see their own generation/edit/cost stats; admins see global platform metrics. Lightweight stats are queried in real-time; heavy aggregations (trends, model breakdowns, cost estimates) are pre-computed hourly by an APScheduler job into a snapshot table.

**Goal:** Provide usage insights, model performance breakdown, cost estimation (cloud fixed-rate + local VRAM-time), agent vs user comparison, template effectiveness tracking, and storage usage — all within an LCARS-themed analytics tab using CSS-only bar charts.

## Scope

Six analytics areas:
1. **Usage stats** — generation/edit/batch counts, media type distribution, daily/weekly trends
2. **Model performance** — per-model usage counts, success/failure rates, average duration
3. **Cost estimation** — per-model fixed cloud rates + VRAM-time local rates, togglable
4. **Agent vs user comparison** — side-by-side generation counts and costs
5. **Template effectiveness** — template run counts, success rates, per-template breakdown
6. **Storage usage** — total bytes used, breakdown by media type

## Database Schema

### New table: `media_analytics_snapshots`

```sql
CREATE TABLE IF NOT EXISTS media_analytics_snapshots (
    id SERIAL PRIMARY KEY,
    period_type VARCHAR(10) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    scope_type VARCHAR(20) DEFAULT 'global',
    scope_id INTEGER DEFAULT 0,
    metrics JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(period_type, period_start, scope_type, scope_id)
);
```

`metrics` JSONB structure:
```json
{
  "generation_count": 42,
  "edit_count": 15,
  "batch_count": 3,
  "by_media_type": {"image": 35, "video": 7},
  "by_model": {"sd_xl_base_1.0": 30, "RealESRGAN_x4plus": 12},
  "by_edit_type": {"upscale": 8, "inpaint": 4, "img2img": 3},
  "success_rate": 0.95,
  "avg_duration_ms": 12400,
  "cost_fixed": 0.084,
  "cost_vram_time": 0.021,
  "storage_bytes": 524288000,
  "template_runs": 5,
  "template_success_rate": 0.80
}
```

### New table: `media_cost_rates`

```sql
CREATE TABLE IF NOT EXISTS media_cost_rates (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    cost_per_generation NUMERIC(10,6) DEFAULT 0,
    vram_gb_per_sec NUMERIC(10,6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

Seeded with defaults for known models (SDXL, RealESRGAN, AnimateDiff, etc.).

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_analytics_snap_period ON media_analytics_snapshots(period_type, period_start);
CREATE INDEX IF NOT EXISTS idx_analytics_snap_scope ON media_analytics_snapshots(scope_type, scope_id);
```

## Analytics Service

**New file:** `platform_v2/tools/media_studio/services/analytics_service.py` (~250 lines)

### Real-time functions (query live tables)

#### `get_realtime_stats(owner_type=None, owner_id=None, date_from=None, date_to=None)`
Quick counts from live tables within date range:
- Total generations (from `media_library`)
- Total edits (from `media_edits WHERE status='completed'`)
- Total batches (from `media_batches`)
- Active pipelines (from `media_pipeline_executions WHERE status='running'`)
- Storage used (COUNT * average estimate from `media_library`)

Returns flat dict. Scoped by owner if provided, otherwise global.

#### `get_recent_activity(owner_type=None, owner_id=None, limit=20)`
Last N generations/edits with timestamp, type, model, status. Combines `media_library` and `media_edits` ordered by created_at DESC.

### Pre-computed functions (read from snapshots)

#### `get_trend_data(period_type, scope_type, scope_id, date_from, date_to)`
SELECT from `media_analytics_snapshots` for the date range. Returns list of `{period_start, metrics}` dicts for charting.

#### `get_model_breakdown(scope_type, scope_id, date_from, date_to)`
Aggregate `by_model` from snapshot metrics across the date range. Returns `{model_name: count}` sorted by count DESC.

#### `get_cost_summary(scope_type, scope_id, date_from, date_to, mode='fixed')`
Sum `cost_fixed` or `cost_vram_time` from snapshots. Also return per-model breakdown. Returns `{total, by_model: {name: cost}}`.

#### `get_agent_vs_user(date_from, date_to)`
Compare snapshot metrics for `scope_type='user'` vs `scope_type='agent'`. Returns `{user: {count, cost}, agent: {count, cost}}`.

#### `get_template_stats(scope_type, scope_id, date_from, date_to)`
Aggregate template_runs and template_success_rate from snapshots. Also query `media_pipeline_executions` for per-template breakdown.

### Admin functions

#### `get_cost_rates()`
SELECT all from `media_cost_rates`. Return list of dicts.

#### `update_cost_rate(model_name, cost_per_generation=None, vram_gb_per_sec=None)`
UPSERT into `media_cost_rates`. Return success/error.

### Aggregation function (called by APScheduler)

#### `compute_snapshot(period_type='hourly')`
1. Determine period bounds (last hour or last day)
2. Query `media_library`, `media_edits`, `media_batches`, `media_pipeline_executions` for that period
3. Group by owner to create per-user and per-agent snapshots
4. Create global snapshot (sum of all)
5. Compute cost estimates by joining with `media_cost_rates`
6. UPSERT into `media_analytics_snapshots` (ON CONFLICT UPDATE)
7. Return count of snapshots written

## APScheduler Job

**Modified file:** `ai_bridge/agent_loop.py`

Add hourly job:
```python
self.scheduler.add_job(
    with_app_context(self._compute_media_analytics),
    trigger=IntervalTrigger(hours=1),
    id="media_analytics_snapshot",
    name="Media Analytics Hourly Snapshot",
    replace_existing=True,
)
```

`_compute_media_analytics` method calls `compute_snapshot(period_type='hourly')`.

Update job count from 21 to 22. Add `"media_analytics_snapshot"` to `stop()` job ID list.

## API Routes

**Modified file:** `platform_v2/tools/media_studio/routes.py`

### New endpoints (6)

#### `GET /api/media-studio/analytics/realtime`
Real-time stats. Query: `?date_from=`, `?date_to=`. Scoped to current user; admins get global with `?scope=global`.
Response: `{generation_count, edit_count, batch_count, active_pipelines, storage_bytes}`

#### `GET /api/media-studio/analytics/trends`
Pre-computed trend data. Query: `?period=hourly|daily`, `?date_from=`, `?date_to=`, `?scope=global`.
Response: `[{period_start, metrics: {...}}, ...]`

#### `GET /api/media-studio/analytics/models`
Model usage breakdown. Query: `?date_from=`, `?date_to=`.
Response: `{by_model: {model_name: count}, by_edit_type: {type: count}}`

#### `GET /api/media-studio/analytics/costs`
Cost summary. Query: `?date_from=`, `?date_to=`, `?mode=fixed|vram`.
Response: `{total, by_model: {name: cost}, mode}`

#### `GET /api/media-studio/analytics/cost-rates`
Admin only. List all cost rate configs.
Response: `[{model_name, cost_per_generation, vram_gb_per_sec, updated_at}]`

#### `PUT /api/media-studio/analytics/cost-rates/<model_name>`
Admin only. Update cost rate for a model.
Body: `{cost_per_generation, vram_gb_per_sec}`
Response: `{success: true}`

## Frontend

**Modified file:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

### Analytics tab

Add 5th button to `#msGalleryFilter`: `Analytics`. When active, hides gallery/templates and shows `#msAnalyticsView`.

### Analytics view layout

**Top bar:** Date range preset buttons (7d, 30d, 90d, All) + custom date inputs + cost mode toggle (Cloud$/Local$).

**Stat cards row:** 4 summary cards — Total Generations, Total Edits, Active Pipelines, Storage Used.

**Charts area** (CSS-only horizontal bar charts):
- **Generation Trends** — daily/hourly count bars over selected range
- **Model Usage** — horizontal bars per model, proportional width + count label
- **Edit Type Breakdown** — bars for each edit type
- **Cost Summary** — total display + per-model cost bars
- **Agent vs User** — side-by-side comparison bars
- **Template Effectiveness** — run counts + success rate bars

**Admin panel** (collapsed, admin only): Editable cost rates table.

### JS functions (~150 lines)

- `loadAnalytics()` — fetch all endpoints, render dashboard
- `setAnalyticsRange(preset)` — set dates from preset, reload
- `setCustomRange()` — read date inputs, reload
- `toggleCostMode(mode)` — switch fixed/vram, reload cost section
- `renderStatCards(data)` — update stat card values
- `renderTrendChart(data)` — CSS bar chart for trends
- `renderModelChart(data)` — horizontal bars for model breakdown
- `renderCostSummary(data)` — cost total + per-model bars
- `loadCostRates()` — admin: render editable rates table
- `saveCostRate(modelName)` — admin: PUT rate update

## CSS

**Modified file:** `platform_v2/tools/media_studio/static/css/media-studio.css`

New styles (~80 lines):
- `.ms-analytics-header` — date range controls bar
- `.ms-analytics-preset-btn` — range preset buttons
- `.ms-analytics-stat-cards` — flex row of summary cards
- `.ms-analytics-stat-card` — card with value + label
- `.ms-analytics-chart` — chart section container
- `.ms-analytics-chart-title` — section header
- `.ms-analytics-bar` — bar chart row
- `.ms-analytics-bar-fill` — proportional fill
- `.ms-analytics-bar-label` — name + count label
- `.ms-analytics-cost-toggle` — mode toggle buttons
- `.ms-analytics-cost-total` — large cost display
- `.ms-analytics-admin` — admin cost rates panel
- `.ms-analytics-rate-row` — editable rate row

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/156_media_analytics.sql` | 2 tables + indexes + seed cost rates |
| **Create** | `platform_v2/tools/media_studio/services/analytics_service.py` | Analytics service (~250 lines) |
| **Modify** | `ai_bridge/agent_loop.py` | Hourly snapshot APScheduler job (#22) |
| **Modify** | `platform_v2/tools/media_studio/routes.py` | 6 endpoints (S24 section) |
| **Modify** | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Analytics view + JS (~150 lines) |
| **Modify** | `platform_v2/tools/media_studio/static/css/media-studio.css` | Analytics styles (~80 lines) |

**Total:** ~530 lines new code, ~30 lines modifications

## Dependencies

None new — all data from existing tables.

## Scope constraints

- No external chart library (CSS bars only)
- No exportable reports
- No real-time websocket updates (loads on tab switch)
- No predictive analytics or ML insights
- No alerting/notifications on cost thresholds
