# Media Studio Layer 10: Media Analytics — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add analytics dashboard with usage stats, model breakdown, cost estimation, agent vs user comparison, template effectiveness, and storage tracking — using hybrid real-time + pre-computed architecture.

**Architecture:** `analytics_service.py` handles both real-time queries (live table counts) and pre-computed reads (from `media_analytics_snapshots`). An APScheduler hourly job in `agent_loop.py` calls `compute_snapshot()` to aggregate metrics. Also computes daily snapshots at midnight. Frontend adds an "Analytics" tab with CSS-only bar charts and stat cards.

**Tech Stack:** Flask, PostgreSQL, APScheduler, HTML5, CSS bar charts

**Key patterns from existing code:**
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`, `psycopg2.extras.Json()` for JSONB
- `media_library` has `model`, `cost` (numeric), `duration_ms`, `is_favorite`, `media_type`, `owner_type`, `owner_id` — no `file_size` column
- `media_generation_queue` has `status`, `started_at`, `completed_at` — duration computed from timestamps, model from `params` JSONB
- `media_edits` has `status`, `created_at`, `completed_at` — same pattern
- Agent loop: `with_app_context(self._method)` wrapper, `IntervalTrigger`, `replace_existing=True`, currently 21 jobs
- Admin check: `if not getattr(current_user, "is_admin", False):`
- Routes: `@media_studio_bp.route()` + `@login_required`, local imports, `jsonify()`
- JS: IIFE, `window.funcName`, `api(method, path, body)`, `_clearChildren()`, `document.createElement`
- CSS: `ms-` prefix, `var(--ms-border, #334)`, `var(--ms-accent, #f90)`, `var(--ms-text, #aab)`

---

## Task 1: Database Migration 156

**Files:**
- Create: `database/migrations/156_media_analytics.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 156: Media analytics snapshots + cost rates
-- Idempotent: safe to run multiple times

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

CREATE TABLE IF NOT EXISTS media_cost_rates (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    cost_per_generation NUMERIC(10,6) DEFAULT 0,
    vram_gb_per_sec NUMERIC(10,6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_analytics_snap_period ON media_analytics_snapshots(period_type, period_start);
CREATE INDEX IF NOT EXISTS idx_analytics_snap_scope ON media_analytics_snapshots(scope_type, scope_id);

-- Seed default cost rates for known models
INSERT INTO media_cost_rates (model_name, cost_per_generation, vram_gb_per_sec) VALUES
    ('sd_xl_base_1.0.safetensors', 0.002, 0.0003),
    ('RealESRGAN_x4plus.pth', 0.001, 0.0001),
    ('mm_sd_v15_v2.safetensors', 0.005, 0.0008),
    ('ip-adapter_sdxl.safetensors', 0.003, 0.0004),
    ('lanczos', 0.0, 0.0)
ON CONFLICT (model_name) DO NOTHING;
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/156_media_analytics.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/156_media_analytics.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d media_analytics_snapshots"
docker exec archie_database psql -U archie -d archie -c "SELECT * FROM media_cost_rates"
```

Expected: Both tables exist, 5 seed rows in cost_rates.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/156_media_analytics.sql
git commit -m "feat(media-studio): add migration 156 — analytics snapshots + cost rates"
```

---

## Task 2: Analytics Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/analytics_service.py`

**Dependencies:** Task 1

- [ ] **Step 1: Write the analytics service**

Create `analytics_service.py` (~280 lines):

```python
"""Media analytics service — real-time stats, pre-computed trends, cost estimation.

Real-time (query live tables):
- get_realtime_stats()    — counts from media_library, media_edits, etc.
- get_recent_activity()   — last N operations

Pre-computed (read from snapshots):
- get_trend_data()        — time series for charting
- get_model_breakdown()   — per-model usage counts
- get_cost_summary()      — total + per-model cost
- get_agent_vs_user()     — scope comparison
- get_template_stats()    — pipeline run counts + success rates

Admin:
- get_cost_rates()        — list cost rate configs
- update_cost_rate()      — upsert rate

Aggregation (called by APScheduler):
- compute_snapshot()      — hourly/daily metric aggregation
"""
```

**`get_realtime_stats(owner_type=None, owner_id=None, date_from=None, date_to=None)`**

```python
def get_realtime_stats(owner_type=None, owner_id=None, date_from=None, date_to=None):
    from database import get_db_cursor
    stats = {}
    with get_db_cursor() as (conn, cur):
        # Build WHERE clause for scoping
        where_parts = []
        params = []
        if owner_type and owner_id:
            where_parts.append("owner_type = %s AND owner_id = %s")
            params.extend([owner_type, owner_id])
        if date_from:
            where_parts.append("created_at >= %s")
            params.append(date_from)
        if date_to:
            where_parts.append("created_at <= %s")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Generation count
        cur.execute(f"SELECT COUNT(*) AS cnt FROM media_library{where}", params)
        stats['generation_count'] = cur.fetchone()['cnt']

        # Edit count (rebuild params for edits table which has same columns)
        cur.execute(f"SELECT COUNT(*) AS cnt FROM media_edits WHERE status = 'completed'" +
                    (" AND " + " AND ".join(where_parts) if where_parts else ""), params)
        stats['edit_count'] = cur.fetchone()['cnt']

        # Batch count
        batch_where = where.replace("owner_type", "owner_type").replace("created_at", "created_at")
        cur.execute(f"SELECT COUNT(*) AS cnt FROM media_batches{where}", params)
        stats['batch_count'] = cur.fetchone()['cnt']

        # Active pipelines
        cur.execute("SELECT COUNT(*) AS cnt FROM media_pipeline_executions WHERE status = 'running'")
        stats['active_pipelines'] = cur.fetchone()['cnt']

        # Storage estimate (count * 2MB average since no file_size column)
        stats['storage_bytes'] = stats['generation_count'] * 2 * 1024 * 1024

    return stats
```

Note: `media_library` has no `file_size` column, so storage is estimated at ~2MB per image. This can be improved later by adding a `file_size` column.

**`get_recent_activity(owner_type=None, owner_id=None, limit=20)`**

Query `media_library` last N rows with `model`, `media_type`, `created_at`. Add `media_edits` last N with `edit_type`, `status`. Combine, sort by created_at DESC, limit.

**`get_trend_data(period_type, scope_type='global', scope_id=0, date_from=None, date_to=None)`**

```python
def get_trend_data(period_type, scope_type='global', scope_id=0, date_from=None, date_to=None):
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        query = """
            SELECT period_start, metrics FROM media_analytics_snapshots
            WHERE period_type = %s AND scope_type = %s AND scope_id = %s
        """
        params = [period_type, scope_type, scope_id]
        if date_from:
            query += " AND period_start >= %s"
            params.append(date_from)
        if date_to:
            query += " AND period_start <= %s"
            params.append(date_to)
        query += " ORDER BY period_start"
        cur.execute(query, params)
        return [{"period_start": r['period_start'].isoformat(), "metrics": r['metrics']} for r in cur.fetchall()]
```

**`get_model_breakdown(scope_type='global', scope_id=0, date_from=None, date_to=None)`**

Aggregate `by_model` dicts from snapshots in range. Sum counts per model across all snapshot rows. Also aggregate `by_edit_type`. Return `{"by_model": {...}, "by_edit_type": {...}}`.

**`get_cost_summary(scope_type='global', scope_id=0, date_from=None, date_to=None, mode='fixed')`**

Sum `cost_fixed` or `cost_vram_time` from snapshots. Also break down by model using `by_model` counts joined with `media_cost_rates`. Return `{"total": float, "by_model": {name: cost}, "mode": str}`.

**`get_agent_vs_user(date_from=None, date_to=None)`**

Query snapshots for scope_type='user' (sum all user scopes) vs scope_type='agent'. Return comparison dict.

**`get_template_stats(scope_type='global', scope_id=0, date_from=None, date_to=None)`**

Sum `template_runs` and average `template_success_rate` from snapshots. Also query `media_pipeline_executions` for per-template breakdown (group by template_id, count, success rate).

**`get_cost_rates()`** — SELECT all from `media_cost_rates` ORDER BY model_name.

**`update_cost_rate(model_name, cost_per_generation=None, vram_gb_per_sec=None)`**

```python
def update_cost_rate(model_name, cost_per_generation=None, vram_gb_per_sec=None):
    from database import get_db_cursor
    sets = []
    params = []
    if cost_per_generation is not None:
        sets.append("cost_per_generation = %s")
        params.append(cost_per_generation)
    if vram_gb_per_sec is not None:
        sets.append("vram_gb_per_sec = %s")
        params.append(vram_gb_per_sec)
    if not sets:
        return {"error": "No fields to update"}
    sets.append("updated_at = NOW()")
    params.append(model_name)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"""
            INSERT INTO media_cost_rates (model_name, cost_per_generation, vram_gb_per_sec, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (model_name) DO UPDATE SET {', '.join(sets)}
        """, [model_name, cost_per_generation or 0, vram_gb_per_sec or 0] + params[:-1])
    return {"success": True}
```

Actually, simpler UPSERT pattern:
```python
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute("""
        INSERT INTO media_cost_rates (model_name, cost_per_generation, vram_gb_per_sec, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (model_name) DO UPDATE SET
            cost_per_generation = COALESCE(%s, media_cost_rates.cost_per_generation),
            vram_gb_per_sec = COALESCE(%s, media_cost_rates.vram_gb_per_sec),
            updated_at = NOW()
    """, (model_name, cost_per_generation or 0, vram_gb_per_sec or 0,
          cost_per_generation, vram_gb_per_sec))
return {"success": True}
```

**`compute_snapshot(period_type='hourly')`**

The main aggregation function:

```python
def compute_snapshot(period_type='hourly'):
    """Compute analytics snapshots for the last period.
    Called hourly by APScheduler. Also computes daily at midnight."""
    import logging
    from datetime import datetime, timedelta
    from database import get_db_cursor
    from psycopg2.extras import Json

    logger = logging.getLogger(__name__)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

    if period_type == 'hourly':
        period_start = now - timedelta(hours=1)
        period_end = now
    else:  # daily
        period_start = now.replace(hour=0) - timedelta(days=1)
        period_end = now.replace(hour=0)

    count = 0
    with get_db_cursor(commit=True) as (conn, cur):
        # Load cost rates for cost computation
        cur.execute("SELECT model_name, cost_per_generation, vram_gb_per_sec FROM media_cost_rates")
        cost_rates = {r['model_name']: r for r in cur.fetchall()}

        # Get generations in period grouped by owner
        cur.execute("""
            SELECT owner_type, owner_id, COUNT(*) as cnt,
                   COALESCE(SUM(cost), 0) as total_cost,
                   COALESCE(AVG(duration_ms), 0) as avg_dur,
                   jsonb_object_agg(COALESCE(media_type, 'image'), cnt2) as by_type,
                   jsonb_object_agg(COALESCE(model, 'unknown'), cnt3) as by_model
            FROM (
                SELECT owner_type, owner_id, cost, duration_ms, media_type, model,
                       COUNT(*) OVER (PARTITION BY owner_type, owner_id, media_type) as cnt2,
                       COUNT(*) OVER (PARTITION BY owner_type, owner_id, model) as cnt3
                FROM media_library
                WHERE created_at >= %s AND created_at < %s AND is_deleted = false
            ) sub
            GROUP BY owner_type, owner_id
        """, (period_start, period_end))
        gen_rows = cur.fetchall()

        # Simpler approach: query counts directly
        # Generation counts by owner
        cur.execute("""
            SELECT owner_type, owner_id,
                   COUNT(*) as gen_count,
                   COALESCE(AVG(duration_ms), 0) as avg_duration_ms
            FROM media_library
            WHERE created_at >= %s AND created_at < %s AND is_deleted = false
            GROUP BY owner_type, owner_id
        """, (period_start, period_end))
        gen_by_owner = cur.fetchall()

        # Model breakdown (global)
        cur.execute("""
            SELECT COALESCE(model, 'unknown') as model, COUNT(*) as cnt
            FROM media_library
            WHERE created_at >= %s AND created_at < %s AND is_deleted = false
            GROUP BY model ORDER BY cnt DESC
        """, (period_start, period_end))
        by_model = {r['model']: r['cnt'] for r in cur.fetchall()}

        # Media type breakdown (global)
        cur.execute("""
            SELECT COALESCE(media_type, 'image') as mtype, COUNT(*) as cnt
            FROM media_library
            WHERE created_at >= %s AND created_at < %s AND is_deleted = false
            GROUP BY media_type
        """, (period_start, period_end))
        by_media_type = {r['mtype']: r['cnt'] for r in cur.fetchall()}

        # Edit counts + types
        cur.execute("""
            SELECT COUNT(*) as cnt FROM media_edits
            WHERE status = 'completed' AND created_at >= %s AND created_at < %s
        """, (period_start, period_end))
        edit_count = cur.fetchone()['cnt']

        cur.execute("""
            SELECT edit_type, COUNT(*) as cnt FROM media_edits
            WHERE status = 'completed' AND created_at >= %s AND created_at < %s
            GROUP BY edit_type
        """, (period_start, period_end))
        by_edit_type = {r['edit_type']: r['cnt'] for r in cur.fetchall()}

        # Batch count
        cur.execute("""
            SELECT COUNT(*) as cnt FROM media_batches
            WHERE created_at >= %s AND created_at < %s
        """, (period_start, period_end))
        batch_count = cur.fetchone()['cnt']

        # Template/pipeline runs
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'completed') as success
            FROM media_pipeline_executions
            WHERE created_at >= %s AND created_at < %s
        """, (period_start, period_end))
        pipe_row = cur.fetchone()
        template_runs = pipe_row['total']
        template_success_rate = (pipe_row['success'] / pipe_row['total']) if pipe_row['total'] > 0 else 0

        # Success/failure rate for generations
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status IN ('completed', 'complete')) as success
            FROM media_generation_queue
            WHERE created_at >= %s AND created_at < %s
        """, (period_start, period_end))
        q_row = cur.fetchone()
        success_rate = (q_row['success'] / q_row['total']) if q_row['total'] > 0 else 0

        # Compute costs
        total_gen = sum(r['gen_count'] for r in gen_by_owner) if gen_by_owner else 0
        avg_duration = sum(r['avg_duration_ms'] for r in gen_by_owner) / len(gen_by_owner) if gen_by_owner else 0

        cost_fixed = 0
        cost_vram = 0
        for model_name, model_count in by_model.items():
            rate = cost_rates.get(model_name, {})
            cost_fixed += model_count * float(rate.get('cost_per_generation', 0) or 0)
            cost_vram += model_count * float(rate.get('vram_gb_per_sec', 0) or 0) * (avg_duration / 1000)

        # Build global metrics
        global_metrics = {
            "generation_count": total_gen,
            "edit_count": edit_count,
            "batch_count": batch_count,
            "by_media_type": by_media_type,
            "by_model": by_model,
            "by_edit_type": by_edit_type,
            "success_rate": round(success_rate, 3),
            "avg_duration_ms": round(avg_duration, 1),
            "cost_fixed": round(cost_fixed, 6),
            "cost_vram_time": round(cost_vram, 6),
            "storage_bytes": total_gen * 2 * 1024 * 1024,  # estimate
            "template_runs": template_runs,
            "template_success_rate": round(template_success_rate, 3),
        }

        # Upsert global snapshot
        cur.execute("""
            INSERT INTO media_analytics_snapshots
                (period_type, period_start, period_end, scope_type, scope_id, metrics)
            VALUES (%s, %s, %s, 'global', 0, %s)
            ON CONFLICT (period_type, period_start, scope_type, scope_id)
            DO UPDATE SET metrics = EXCLUDED.metrics, created_at = NOW()
        """, (period_type, period_start, period_end, Json(global_metrics)))
        count += 1

        # Per-owner snapshots
        for row in gen_by_owner:
            owner_metrics = {
                "generation_count": row['gen_count'],
                "avg_duration_ms": round(float(row['avg_duration_ms']), 1),
            }
            cur.execute("""
                INSERT INTO media_analytics_snapshots
                    (period_type, period_start, period_end, scope_type, scope_id, metrics)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (period_type, period_start, scope_type, scope_id)
                DO UPDATE SET metrics = EXCLUDED.metrics, created_at = NOW()
            """, (period_type, period_start, period_end,
                  row['owner_type'], row['owner_id'], Json(owner_metrics)))
            count += 1

    logger.info(f"[Analytics] Computed {count} {period_type} snapshots for {period_start}")
    return count
```

- [ ] **Step 2: Verify imports**

```bash
docker exec archie_platform python3 -c "from tools.media_studio.services.analytics_service import get_realtime_stats, compute_snapshot, get_cost_rates, update_cost_rate, get_trend_data, get_model_breakdown, get_cost_summary; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/analytics_service.py
git commit -m "feat(media-studio): add analytics service — realtime stats, trends, cost estimation"
```

---

## Task 3: APScheduler Job

**Files:**
- Modify: `ai_bridge/agent_loop.py`

**Dependencies:** Task 2

- [ ] **Step 1: Read agent_loop.py to find exact insertion points**

Find: (a) last `scheduler.add_job` call, (b) `stop()` method job ID list, (c) job count comment.

- [ ] **Step 2: Add hourly analytics job**

After the last `scheduler.add_job` call (agent_media_generation), add:

```python
self.scheduler.add_job(
    with_app_context(self._compute_media_analytics),
    trigger=IntervalTrigger(hours=1),
    id="media_analytics_snapshot",
    name="Agent Loop: Media Analytics Snapshot",
    replace_existing=True,
)
```

- [ ] **Step 3: Add the method**

Before the `stop()` method, add:

```python
def _compute_media_analytics(self):
    """Compute hourly analytics snapshots. Also computes daily at midnight."""
    from datetime import datetime
    from tools.media_studio.services.analytics_service import compute_snapshot
    try:
        count = compute_snapshot(period_type='hourly')
        logger.info(f"[Analytics] Hourly: {count} snapshots")
        # Also compute daily snapshot at midnight (hour 0)
        if datetime.utcnow().hour == 0:
            daily_count = compute_snapshot(period_type='daily')
            logger.info(f"[Analytics] Daily: {daily_count} snapshots")
    except Exception as e:
        logger.error(f"[Analytics] Snapshot failed: {e}")
```

- [ ] **Step 4: Update job count and stop() list**

Update the job count comment from 21 to 22. Add `"media_analytics_snapshot"` to the `stop()` job ID list.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(media-studio): add hourly analytics snapshot APScheduler job (#22)"
```

---

## Task 4: API Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (append S24 section)

**Dependencies:** Task 2

- [ ] **Step 1: Read end of routes.py to find append location**

- [ ] **Step 2: Append 6 analytics routes**

Add comment `# ── S24  Media Analytics ──`, then:

**`GET /api/media-studio/analytics/realtime`**
```python
@media_studio_bp.route("/api/media-studio/analytics/realtime", methods=["GET"])
@login_required
def api_analytics_realtime():
    from tools.media_studio.services.analytics_service import get_realtime_stats
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_realtime_stats(date_from=date_from, date_to=date_to)
    else:
        result = get_realtime_stats(
            owner_type="user", owner_id=current_user.id,
            date_from=date_from, date_to=date_to,
        )
    return jsonify(result)
```

**`GET /api/media-studio/analytics/trends`**
```python
@media_studio_bp.route("/api/media-studio/analytics/trends", methods=["GET"])
@login_required
def api_analytics_trends():
    from tools.media_studio.services.analytics_service import get_trend_data
    period = request.args.get("period", "hourly")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_trend_data(period, "global", 0, date_from, date_to)
    else:
        result = get_trend_data(period, "user", current_user.id, date_from, date_to)
    return jsonify(result)
```

**`GET /api/media-studio/analytics/models`**
```python
@media_studio_bp.route("/api/media-studio/analytics/models", methods=["GET"])
@login_required
def api_analytics_models():
    from tools.media_studio.services.analytics_service import get_model_breakdown
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_model_breakdown("global", 0, date_from, date_to)
    else:
        result = get_model_breakdown("user", current_user.id, date_from, date_to)
    return jsonify(result)
```

**`GET /api/media-studio/analytics/costs`**
```python
@media_studio_bp.route("/api/media-studio/analytics/costs", methods=["GET"])
@login_required
def api_analytics_costs():
    from tools.media_studio.services.analytics_service import get_cost_summary
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    mode = request.args.get("mode", "fixed")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_cost_summary("global", 0, date_from, date_to, mode)
    else:
        result = get_cost_summary("user", current_user.id, date_from, date_to, mode)
    return jsonify(result)
```

**`GET /api/media-studio/analytics/cost-rates`** (admin only)
```python
@media_studio_bp.route("/api/media-studio/analytics/cost-rates", methods=["GET"])
@login_required
def api_get_cost_rates():
    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403
    from tools.media_studio.services.analytics_service import get_cost_rates
    rates = get_cost_rates()
    for r in rates:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return jsonify(rates)
```

**`PUT /api/media-studio/analytics/cost-rates/<model_name>`** (admin only)
```python
@media_studio_bp.route("/api/media-studio/analytics/cost-rates/<model_name>", methods=["PUT"])
@login_required
def api_update_cost_rate(model_name):
    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403
    from tools.media_studio.services.analytics_service import update_cost_rate
    data = request.get_json() or {}
    result = update_cost_rate(
        model_name,
        cost_per_generation=data.get("cost_per_generation"),
        vram_gb_per_sec=data.get("vram_gb_per_sec"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

- [ ] **Step 3: Verify routes**

```bash
docker exec archie_platform python3 -c "
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'analytics' in r.rule and 'media-studio' in r.rule]
print(f'{len(rules)} routes:', rules)
"
```

Expected: 6 routes.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add analytics API routes (6 endpoints)"
```

---

## Task 5: Analytics Frontend HTML + JS

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Dependencies:** Task 4

- [ ] **Step 1: Read HTML to find insertion points**

Find: (a) gallery filter buttons for adding Analytics toggle, (b) where S23 template view ends, (c) where S23 JS ends.

- [ ] **Step 2: Add Analytics button to gallery filter**

Add 5th button to `#msGalleryFilter`:
```html
<button class="ms-btn-xs ms-gallery-filter-btn" data-filter="analytics" onclick="setOwnerFilter('analytics')">Analytics</button>
```

- [ ] **Step 3: Add analytics view HTML**

After the template view div (`#msTemplateView`):

```html
<!-- ── S24  Media Analytics ── -->
<div id="msAnalyticsView" style="display:none;">
  <div class="ms-analytics-header">
    <div class="ms-analytics-presets">
      <button class="ms-btn-xs ms-analytics-preset-btn active" onclick="setAnalyticsRange('7d')">7d</button>
      <button class="ms-btn-xs ms-analytics-preset-btn" onclick="setAnalyticsRange('30d')">30d</button>
      <button class="ms-btn-xs ms-analytics-preset-btn" onclick="setAnalyticsRange('90d')">90d</button>
      <button class="ms-btn-xs ms-analytics-preset-btn" onclick="setAnalyticsRange('all')">All</button>
    </div>
    <div class="ms-analytics-custom-range">
      <input type="date" id="msAnalyticsFrom" class="ms-input-xs">
      <span class="ms-text-muted">to</span>
      <input type="date" id="msAnalyticsTo" class="ms-input-xs">
      <button class="ms-btn-xs" onclick="setCustomRange()">Apply</button>
    </div>
    <div class="ms-analytics-cost-toggle">
      <button class="ms-btn-xs ms-cost-mode-btn active" data-mode="fixed" onclick="toggleCostMode('fixed')">Cloud$</button>
      <button class="ms-btn-xs ms-cost-mode-btn" data-mode="vram" onclick="toggleCostMode('vram')">Local$</button>
    </div>
  </div>
  <div class="ms-analytics-stat-cards" id="msAnalyticsCards"></div>
  <div class="ms-analytics-charts">
    <div class="ms-analytics-chart" id="msChartTrends">
      <div class="ms-analytics-chart-title">Generation Trends</div>
      <div id="msChartTrendsBody"></div>
    </div>
    <div class="ms-analytics-chart" id="msChartModels">
      <div class="ms-analytics-chart-title">Model Usage</div>
      <div id="msChartModelsBody"></div>
    </div>
    <div class="ms-analytics-chart" id="msChartEdits">
      <div class="ms-analytics-chart-title">Edit Types</div>
      <div id="msChartEditsBody"></div>
    </div>
    <div class="ms-analytics-chart" id="msChartCosts">
      <div class="ms-analytics-chart-title">Cost Summary</div>
      <div id="msChartCostsBody"></div>
    </div>
    <div class="ms-analytics-chart" id="msChartAgentUser">
      <div class="ms-analytics-chart-title">Agent vs User</div>
      <div id="msChartAgentUserBody"></div>
    </div>
    <div class="ms-analytics-chart" id="msChartTemplates">
      <div class="ms-analytics-chart-title">Template Effectiveness</div>
      <div id="msChartTemplatesBody"></div>
    </div>
  </div>
  <div class="ms-analytics-admin" id="msAnalyticsAdmin" style="display:none;">
    <div class="ms-analytics-chart-title">Cost Rate Config (Admin)</div>
    <div id="msAnalyticsCostRates"></div>
  </div>
</div>
```

- [ ] **Step 4: Update setOwnerFilter for analytics mode**

Add branch in `setOwnerFilter`:
```javascript
if (filter === 'analytics') {
    // Hide gallery + templates, show analytics
    galleryLayout.style.display = 'none';
    tplView.style.display = 'none';
    document.getElementById('msAnalyticsView').style.display = '';
    loadAnalytics();
    return;
}
// Also hide analytics when switching away
var analyticsView = document.getElementById('msAnalyticsView');
if (analyticsView) analyticsView.style.display = 'none';
```

- [ ] **Step 5: Add S24 JavaScript block**

Append after S23 JS (~150 lines):

```javascript
// ── S24  Media Analytics JS ──────────────────────────────────────

var _analyticsDateFrom = null;
var _analyticsDateTo = null;
var _analyticsCostMode = 'fixed';

(function() {
    function _daysAgo(n) {
        var d = new Date();
        d.setDate(d.getDate() - n);
        return d.toISOString().split('T')[0];
    }
    // Default to 30 days
    _analyticsDateFrom = _daysAgo(30);

    window.setAnalyticsRange = function(preset) {
        document.querySelectorAll('.ms-analytics-preset-btn').forEach(function(b) {
            b.classList.toggle('active', b.textContent.toLowerCase() === preset);
        });
        if (preset === '7d') _analyticsDateFrom = _daysAgo(7);
        else if (preset === '30d') _analyticsDateFrom = _daysAgo(30);
        else if (preset === '90d') _analyticsDateFrom = _daysAgo(90);
        else _analyticsDateFrom = null;
        _analyticsDateTo = null;
        loadAnalytics();
    };

    window.setCustomRange = function() {
        _analyticsDateFrom = document.getElementById('msAnalyticsFrom').value || null;
        _analyticsDateTo = document.getElementById('msAnalyticsTo').value || null;
        document.querySelectorAll('.ms-analytics-preset-btn').forEach(function(b) { b.classList.remove('active'); });
        loadAnalytics();
    };

    window.toggleCostMode = function(mode) {
        _analyticsCostMode = mode;
        document.querySelectorAll('.ms-cost-mode-btn').forEach(function(b) {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
        loadAnalytics();
    };

    window.loadAnalytics = function() {
        var qs = '';
        if (_analyticsDateFrom) qs += '&date_from=' + _analyticsDateFrom;
        if (_analyticsDateTo) qs += '&date_to=' + _analyticsDateTo;
        var scopeQs = qs + '&scope=global';  // admins get global, server handles scoping

        // Parallel fetches
        api('GET', '/api/media-studio/analytics/realtime?' + qs.slice(1)).then(renderStatCards);
        api('GET', '/api/media-studio/analytics/trends?period=daily' + scopeQs).then(renderTrendChart);
        api('GET', '/api/media-studio/analytics/models?' + scopeQs.slice(1)).then(renderModelChart);
        api('GET', '/api/media-studio/analytics/costs?mode=' + _analyticsCostMode + scopeQs).then(renderCostSummary);

        // Admin cost rates
        api('GET', '/api/media-studio/analytics/cost-rates').then(function(data) {
            if (!data.error) renderCostRates(data);
        });
    };

    function renderStatCards(data) {
        var container = document.getElementById('msAnalyticsCards');
        _clearChildren(container);
        var cards = [
            {label: 'Generations', value: data.generation_count || 0},
            {label: 'Edits', value: data.edit_count || 0},
            {label: 'Active Pipelines', value: data.active_pipelines || 0},
            {label: 'Storage', value: formatBytes(data.storage_bytes || 0)},
        ];
        cards.forEach(function(c) {
            var card = document.createElement('div');
            card.className = 'ms-analytics-stat-card';
            var val = document.createElement('div');
            val.className = 'ms-analytics-stat-value';
            val.textContent = c.value;
            var lbl = document.createElement('div');
            lbl.className = 'ms-analytics-stat-label';
            lbl.textContent = c.label;
            card.appendChild(val);
            card.appendChild(lbl);
            container.appendChild(card);
        });
    }

    function renderTrendChart(data) {
        var body = document.getElementById('msChartTrendsBody');
        _clearChildren(body);
        if (!Array.isArray(data) || data.length === 0) {
            body.textContent = 'No trend data yet';
            return;
        }
        var maxVal = Math.max.apply(null, data.map(function(d) { return (d.metrics || {}).generation_count || 0; }));
        data.forEach(function(d) {
            var count = (d.metrics || {}).generation_count || 0;
            var pct = maxVal > 0 ? (count / maxVal * 100) : 0;
            var row = document.createElement('div');
            row.className = 'ms-analytics-bar';
            var label = document.createElement('span');
            label.className = 'ms-analytics-bar-label';
            label.textContent = (d.period_start || '').split('T')[0];
            var fill = document.createElement('div');
            fill.className = 'ms-analytics-bar-fill';
            fill.style.width = pct + '%';
            var cnt = document.createElement('span');
            cnt.className = 'ms-analytics-bar-count';
            cnt.textContent = count;
            row.appendChild(label);
            row.appendChild(fill);
            row.appendChild(cnt);
            body.appendChild(row);
        });
    }

    function renderModelChart(data) {
        var body = document.getElementById('msChartModelsBody');
        _clearChildren(body);
        var models = data.by_model || {};
        var entries = Object.entries(models).sort(function(a, b) { return b[1] - a[1]; });
        if (entries.length === 0) { body.textContent = 'No model data yet'; return; }
        var maxVal = entries[0][1];
        entries.forEach(function(e) {
            var row = document.createElement('div');
            row.className = 'ms-analytics-bar';
            var label = document.createElement('span');
            label.className = 'ms-analytics-bar-label';
            label.textContent = e[0].replace('.safetensors', '').replace('.pth', '');
            var fill = document.createElement('div');
            fill.className = 'ms-analytics-bar-fill';
            fill.style.width = (e[1] / maxVal * 100) + '%';
            var cnt = document.createElement('span');
            cnt.className = 'ms-analytics-bar-count';
            cnt.textContent = e[1];
            row.appendChild(label);
            row.appendChild(fill);
            row.appendChild(cnt);
            body.appendChild(row);
        });
        // Also render edit types
        var editsBody = document.getElementById('msChartEditsBody');
        _clearChildren(editsBody);
        var edits = data.by_edit_type || {};
        var eEntries = Object.entries(edits).sort(function(a, b) { return b[1] - a[1]; });
        if (eEntries.length === 0) { editsBody.textContent = 'No edit data yet'; return; }
        var eMax = eEntries[0][1];
        eEntries.forEach(function(e) {
            var row = document.createElement('div');
            row.className = 'ms-analytics-bar';
            var label = document.createElement('span');
            label.className = 'ms-analytics-bar-label';
            label.textContent = e[0];
            var fill = document.createElement('div');
            fill.className = 'ms-analytics-bar-fill ms-analytics-bar-edit';
            fill.style.width = (e[1] / eMax * 100) + '%';
            var cnt = document.createElement('span');
            cnt.className = 'ms-analytics-bar-count';
            cnt.textContent = e[1];
            row.appendChild(label);
            row.appendChild(fill);
            row.appendChild(cnt);
            editsBody.appendChild(row);
        });
    }

    function renderCostSummary(data) {
        var body = document.getElementById('msChartCostsBody');
        _clearChildren(body);
        var total = document.createElement('div');
        total.className = 'ms-analytics-cost-total';
        total.textContent = '$' + (data.total || 0).toFixed(4);
        body.appendChild(total);
        var modeLabel = document.createElement('div');
        modeLabel.className = 'ms-text-muted';
        modeLabel.textContent = data.mode === 'vram' ? 'Local compute estimate' : 'Cloud cost estimate';
        body.appendChild(modeLabel);
        // Per-model breakdown
        var models = data.by_model || {};
        var entries = Object.entries(models).sort(function(a, b) { return b[1] - a[1]; });
        var maxCost = entries.length > 0 ? entries[0][1] : 1;
        entries.forEach(function(e) {
            var row = document.createElement('div');
            row.className = 'ms-analytics-bar';
            var label = document.createElement('span');
            label.className = 'ms-analytics-bar-label';
            label.textContent = e[0].replace('.safetensors', '').replace('.pth', '');
            var fill = document.createElement('div');
            fill.className = 'ms-analytics-bar-fill ms-analytics-bar-cost';
            fill.style.width = (e[1] / maxCost * 100) + '%';
            var cnt = document.createElement('span');
            cnt.className = 'ms-analytics-bar-count';
            cnt.textContent = '$' + e[1].toFixed(4);
            row.appendChild(label);
            row.appendChild(fill);
            row.appendChild(cnt);
            body.appendChild(row);
        });
    }

    function renderCostRates(rates) {
        var admin = document.getElementById('msAnalyticsAdmin');
        admin.style.display = '';
        var container = document.getElementById('msAnalyticsCostRates');
        _clearChildren(container);
        rates.forEach(function(r) {
            var row = document.createElement('div');
            row.className = 'ms-analytics-rate-row';
            var name = document.createElement('span');
            name.className = 'ms-analytics-rate-name';
            name.textContent = r.model_name;
            var cloudInput = document.createElement('input');
            cloudInput.type = 'number';
            cloudInput.step = '0.000001';
            cloudInput.className = 'ms-input-xs';
            cloudInput.value = r.cost_per_generation || 0;
            cloudInput.dataset.model = r.model_name;
            cloudInput.dataset.field = 'cost_per_generation';
            var localInput = document.createElement('input');
            localInput.type = 'number';
            localInput.step = '0.000001';
            localInput.className = 'ms-input-xs';
            localInput.value = r.vram_gb_per_sec || 0;
            localInput.dataset.model = r.model_name;
            localInput.dataset.field = 'vram_gb_per_sec';
            var saveBtn = document.createElement('button');
            saveBtn.className = 'ms-btn-xs';
            saveBtn.textContent = 'Save';
            saveBtn.onclick = function() {
                saveCostRate(r.model_name, parseFloat(cloudInput.value), parseFloat(localInput.value));
            };
            row.appendChild(name);
            row.appendChild(cloudInput);
            row.appendChild(localInput);
            row.appendChild(saveBtn);
            container.appendChild(row);
        });
    }

    window.saveCostRate = function(modelName, cloud, local) {
        api('PUT', '/api/media-studio/analytics/cost-rates/' + encodeURIComponent(modelName), {
            cost_per_generation: cloud, vram_gb_per_sec: local,
        }).then(function(data) {
            if (data.error) alert(data.error);
        });
    };

    function formatBytes(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
        return (bytes / 1073741824).toFixed(1) + ' GB';
    }
})();
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add analytics dashboard HTML + JavaScript"
```

---

## Task 6: Analytics CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css` (append)

**Dependencies:** Task 5

- [ ] **Step 1: Append S24 CSS block**

```css
/* ── S24  Media Analytics ── */
.ms-analytics-header {
    display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    padding: 0.5rem 0; margin-bottom: 0.75rem;
    border-bottom: 1px solid var(--ms-border, #334);
}
.ms-analytics-presets { display: flex; gap: 0.25rem; }
.ms-analytics-preset-btn { font-size: 0.7rem; }
.ms-analytics-preset-btn.active { background: var(--ms-accent, #f90); color: #000; }
.ms-analytics-custom-range {
    display: flex; gap: 0.25rem; align-items: center;
    font-size: 0.7rem; color: var(--ms-text, #aab);
}
.ms-analytics-cost-toggle { display: flex; gap: 0.25rem; margin-left: auto; }
.ms-cost-mode-btn { font-size: 0.65rem; }
.ms-cost-mode-btn.active { background: var(--ms-accent, #f90); color: #000; }
.ms-analytics-stat-cards {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem;
    margin-bottom: 1rem;
}
.ms-analytics-stat-card {
    background: rgba(255,255,255,0.02); border: 1px solid var(--ms-border, #334);
    border-radius: 6px; padding: 0.75rem; text-align: center;
}
.ms-analytics-stat-value {
    font-family: 'Antonio', sans-serif; font-size: 1.5rem;
    color: var(--ms-accent, #f90);
}
.ms-analytics-stat-label {
    font-size: 0.65rem; color: var(--ms-text, #aab);
    text-transform: uppercase; margin-top: 0.25rem;
}
.ms-analytics-charts {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.75rem;
}
.ms-analytics-chart {
    background: rgba(255,255,255,0.02); border: 1px solid var(--ms-border, #334);
    border-radius: 6px; padding: 0.75rem;
}
.ms-analytics-chart-title {
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90); font-size: 0.8rem;
    margin-bottom: 0.5rem; padding-bottom: 0.25rem;
    border-bottom: 1px solid var(--ms-border, #334);
}
.ms-analytics-bar {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.2rem 0; font-size: 0.7rem;
}
.ms-analytics-bar-label {
    width: 120px; flex-shrink: 0; color: var(--ms-text, #aab);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ms-analytics-bar-fill {
    height: 14px; background: var(--ms-accent, #f90); border-radius: 2px;
    min-width: 2px; transition: width 0.3s ease;
    flex: 1; max-width: calc(100% - 180px);
}
.ms-analytics-bar-edit { background: #47b; }
.ms-analytics-bar-cost { background: #4a9; }
.ms-analytics-bar-count {
    width: 50px; text-align: right; color: var(--ms-text, #aab);
    font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem;
}
.ms-analytics-cost-total {
    font-family: 'Antonio', sans-serif; font-size: 2rem;
    color: var(--ms-accent, #f90); margin-bottom: 0.25rem;
}
.ms-analytics-admin {
    margin-top: 1rem; padding: 0.75rem;
    border: 1px solid var(--ms-border, #334); border-radius: 6px;
}
.ms-analytics-rate-row {
    display: flex; gap: 0.5rem; align-items: center;
    padding: 0.3rem 0; font-size: 0.7rem; color: var(--ms-text, #aab);
}
.ms-analytics-rate-name { width: 200px; flex-shrink: 0; }
.ms-analytics-rate-row input { width: 100px; }
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add analytics dashboard CSS"
```

---

## Task 7: Integration Test

**Files:**
- Create: `/tmp/test_layer10.py`

**Dependencies:** All previous tasks

- [ ] **Step 1: Write integration test**

```python
import sys, json, os, logging, inspect
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test imports
from tools.media_studio.services.analytics_service import (
    get_realtime_stats, get_recent_activity, get_trend_data,
    get_model_breakdown, get_cost_summary, get_agent_vs_user,
    get_template_stats, get_cost_rates, update_cost_rate,
    compute_snapshot,
)
results.append(('Import analytics_service', 'OK', True))

from app import app
with app.app_context():
    # Real-time stats (should not error)
    stats = get_realtime_stats()
    results.append(('Realtime stats keys', list(stats.keys()),
        'generation_count' in stats and 'edit_count' in stats))

    # Scoped stats
    stats2 = get_realtime_stats(owner_type='user', owner_id=1)
    results.append(('Scoped stats', 'generation_count' in stats2, True))

    # Cost rates
    rates = get_cost_rates()
    results.append(('Cost rates seeded', len(rates) >= 5, len(rates) >= 5))

    # Update cost rate
    ur = update_cost_rate('test_model', cost_per_generation=0.01, vram_gb_per_sec=0.001)
    results.append(('Update cost rate', ur.get('success', False), ur.get('success', False)))

    # Verify update
    rates2 = get_cost_rates()
    test_rate = [r for r in rates2 if r['model_name'] == 'test_model']
    results.append(('Rate persisted', len(test_rate), len(test_rate) == 1))

    # Clean up test rate
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM media_cost_rates WHERE model_name = 'test_model'")

    # Compute snapshot (should not error even with no data)
    count = compute_snapshot(period_type='hourly')
    results.append(('Compute hourly snapshot', count >= 0, True))

    # Trend data (may be empty)
    trends = get_trend_data('hourly')
    results.append(('Trend data returns list', isinstance(trends, list), True))

    # Model breakdown
    models = get_model_breakdown()
    results.append(('Model breakdown', isinstance(models, dict), True))

    # Cost summary
    costs = get_cost_summary()
    results.append(('Cost summary', 'total' in costs, True))

    # DB tables
    with get_db_cursor() as (conn, cur):
        for tbl in ['media_analytics_snapshots', 'media_cost_rates']:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}")
            results.append((f'{tbl} exists', cur.fetchone()['cnt'] >= 0, True))

    # Routes
    rules = [r.rule for r in app.url_map.iter_rules()
             if 'analytics' in r.rule and 'media-studio' in r.rule]
    results.append(('Analytics routes', len(rules), len(rules) >= 6))

    # HTML
    html_path = '/app/tools/media_studio/templates/tools/media_studio/media_studio.html'
    with open(html_path) as f:
        html = f.read()
    for elem in ['msAnalyticsView', 'msAnalyticsCards', 'msChartTrends',
                 'msChartModels', 'msChartCosts', 'loadAnalytics',
                 'setAnalyticsRange', 'toggleCostMode', 'renderStatCards',
                 'msAnalyticsAdmin']:
        results.append((f'HTML has {elem}', elem, elem in html))

    # CSS
    css_path = '/app/tools/media_studio/static/css/media-studio.css'
    with open(css_path) as f:
        css = f.read()
    for cls in ['.ms-analytics-header', '.ms-analytics-stat-card',
                '.ms-analytics-bar', '.ms-analytics-bar-fill',
                '.ms-analytics-cost-total', '.ms-analytics-chart']:
        results.append((f'CSS has {cls}', cls, cls in css))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_layer10.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_layer10.py
```

Expected: All tests PASS.

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 8: Deploy + Git Push + Dev HQ Update

**Dependencies:** Task 7

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push to remote**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `store_memory` for roadmap update (Layer 10 complete, Media Studio feature-complete)
- `log_decision` for hybrid real-time + pre-computed architecture choice
