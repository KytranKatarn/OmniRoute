# Email Manager Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 6 enhancements to the Email Manager: stats bar with analyze button, background analysis queue, filter/sort controls, bulk actions, auto-check interval, and unread badge on nav.

**Architecture:** All changes are in two files — the frontend template (`email_manager.html`) and the backend routes (`imap_routes.py`). A new `/api/inbox/stats` endpoint provides fetched/analyzed counts. A new `/api/inbox/batch-analyze` endpoint processes unanalyzed emails in small batches via AJAX polling. Bulk actions use a new `/api/inbox/bulk` endpoint. The auto-check interval leverages the existing `check_interval_minutes` IMAP setting with a JS `setInterval`. The nav badge uses a new Jinja2 context variable injected from the route.

**Tech Stack:** Flask, PostgreSQL, Jinja2, vanilla JS, LCARS CSS theme

---

### Task 1: Stats Bar + Analyze Remaining Button

Add a stats bar above the email table showing "191 fetched | 32 analyzed (17%)" with a progress bar and an "Analyze Remaining" button.

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` — add `/api/inbox/stats` endpoint
- Modify: `platform_v2/templates/tools/email_manager.html` — add stats bar HTML, CSS, and JS

**Backend — add stats endpoint:**

Add this route in `imap_routes.py` after the `get_inbox` route (~line 290):

```python
@email_manager_bp.route("/api/inbox/stats", methods=["GET"])
@login_required
def get_inbox_stats():
    """Get inbox stats: total fetched, analyzed, unread."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(ai_analyzed_at) as analyzed,
                COUNT(*) FILTER (WHERE is_read = FALSE AND is_archived = FALSE) as unread,
                COUNT(*) FILTER (WHERE is_archived = TRUE) as archived
            FROM email_inbox
        """)
        stats = dict(cur.fetchone())
        cur.close()
        conn.close()
        return jsonify({"success": True, **stats})
    except Exception as e:
        logger.error(f"Failed to get inbox stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

**Frontend — add stats bar HTML:**

Insert after the `<div class="em-panel-header">` closing `</div>` (line 145), before the category filter bar (line 147):

```html
<!-- Stats Bar -->
<div class="inbox-stats-bar" id="inbox-stats-bar">
    <div class="inbox-stats-left">
        <span class="inbox-stat">
            <i data-lucide="download"></i>
            <span id="stat-total">—</span> fetched
        </span>
        <span class="inbox-stat-divider">|</span>
        <span class="inbox-stat">
            <i data-lucide="brain"></i>
            <span id="stat-analyzed">—</span> analyzed
            <span class="inbox-stat-pct" id="stat-pct"></span>
        </span>
        <span class="inbox-stat-divider">|</span>
        <span class="inbox-stat">
            <i data-lucide="mail"></i>
            <span id="stat-unread">—</span> unread
        </span>
    </div>
    <div class="inbox-stats-right">
        <div class="inbox-stats-progress">
            <div class="inbox-stats-progress-fill" id="stat-progress-fill" style="width: 0%"></div>
        </div>
        <button class="em-btn em-btn--sm em-btn--outline" id="analyze-remaining-btn" onclick="analyzeRemaining()" style="display: none;">
            <i data-lucide="sparkles"></i>
            <span>Analyze Remaining</span>
        </button>
    </div>
</div>
```

**Frontend — add stats bar CSS:**

```css
/* Stats Bar */
.inbox-stats-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    background: rgba(0, 255, 255, 0.03);
    border: 1px solid rgba(0, 255, 255, 0.1);
    border-radius: 8px;
    margin-bottom: 12px;
    gap: 16px;
    flex-wrap: wrap;
}
.inbox-stats-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}
.inbox-stat {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    color: rgba(0, 255, 255, 0.7);
}
.inbox-stat i { width: 14px; height: 14px; }
.inbox-stat span { font-weight: 600; color: #00FFFF; }
.inbox-stat-pct { font-weight: 400 !important; color: rgba(0, 255, 255, 0.5) !important; font-size: 12px; }
.inbox-stat-divider { color: rgba(0, 255, 255, 0.2); }
.inbox-stats-right {
    display: flex;
    align-items: center;
    gap: 12px;
}
.inbox-stats-progress {
    width: 120px;
    height: 6px;
    background: rgba(0, 255, 255, 0.1);
    border-radius: 3px;
    overflow: hidden;
}
.inbox-stats-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #00FFFF, #00CC99);
    border-radius: 3px;
    transition: width 0.5s ease;
}
```

**Frontend — add JS functions:**

```javascript
// ═══════════════════════════════════════════════════════════════════════════════
// INBOX - STATS BAR
// ═══════════════════════════════════════════════════════════════════════════════
async function loadInboxStats() {
    try {
        const resp = await fetch('/tools/email-manager/api/inbox/stats');
        const data = await resp.json();
        if (!data.success) return;

        document.getElementById('stat-total').textContent = data.total;
        document.getElementById('stat-analyzed').textContent = data.analyzed;
        document.getElementById('stat-unread').textContent = data.unread;

        const pct = data.total > 0 ? Math.round((data.analyzed / data.total) * 100) : 0;
        document.getElementById('stat-pct').textContent = '(' + pct + '%)';
        document.getElementById('stat-progress-fill').style.width = pct + '%';

        // Show analyze button if there are unanalyzed emails
        const btn = document.getElementById('analyze-remaining-btn');
        if (data.total > data.analyzed) {
            btn.style.display = '';
            btn.querySelector('span').textContent = 'Analyze ' + (data.total - data.analyzed) + ' Remaining';
        } else {
            btn.style.display = 'none';
        }
    } catch (e) {
        console.error('Stats load error:', e);
    }
}
```

Call `loadInboxStats()` from `DOMContentLoaded` alongside `loadInbox(1)`, and also call it after `loadInbox` completes (at the end of the `loadInbox` function's success path).

**Commit message:** `feat(email): add inbox stats bar with fetched/analyzed counts`

---

### Task 2: Background Batch Analysis

Add a `/api/inbox/batch-analyze` endpoint that analyzes a small batch of unanalyzed emails (5 at a time), and frontend JS that polls it repeatedly when the user clicks "Analyze Remaining".

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` — add `/api/inbox/batch-analyze` endpoint
- Modify: `platform_v2/templates/tools/email_manager.html` — add `analyzeRemaining()` JS with polling

**Backend — add batch-analyze endpoint:**

```python
@email_manager_bp.route("/api/inbox/batch-analyze", methods=["POST"])
@login_required
def batch_analyze():
    """Analyze a batch of unanalyzed emails (5 at a time)."""
    try:
        from email_intelligence import EmailIntelligence

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id FROM email_inbox
            WHERE ai_analyzed_at IS NULL
            ORDER BY received_at DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return jsonify({"success": True, "analyzed": 0, "remaining": 0})

        ei = EmailIntelligence()
        analyzed = 0
        for row in rows:
            try:
                ei.analyze_email(row["id"])
                analyzed += 1
                time.sleep(1)  # GPU safety
            except Exception as e:
                logger.warning(f"Batch analysis failed for #{row['id']}: {e}")

        # Get remaining count
        conn2 = get_db()
        cur2 = conn2.cursor(cursor_factory=RealDictCursor)
        cur2.execute("SELECT COUNT(*) as remaining FROM email_inbox WHERE ai_analyzed_at IS NULL")
        remaining = cur2.fetchone()["remaining"]
        cur2.close()
        conn2.close()

        return jsonify({"success": True, "analyzed": analyzed, "remaining": remaining})
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

Add `import time` at the top of `imap_routes.py` if not already present.

**Frontend — add analyzeRemaining() JS:**

```javascript
let analysisRunning = false;

async function analyzeRemaining() {
    if (analysisRunning) return;
    analysisRunning = true;

    const btn = document.getElementById('analyze-remaining-btn');
    btn.disabled = true;
    const originalText = btn.querySelector('span').textContent;

    async function processBatch() {
        try {
            btn.querySelector('span').textContent = 'Analyzing...';
            const resp = await fetch('/tools/email-manager/api/inbox/batch-analyze', { method: 'POST' });
            const data = await resp.json();

            if (!data.success) {
                showToast(data.error || 'Analysis failed', 'error');
                analysisRunning = false;
                btn.disabled = false;
                btn.querySelector('span').textContent = originalText;
                return;
            }

            // Update stats
            loadInboxStats();

            if (data.remaining > 0) {
                btn.querySelector('span').textContent = 'Analyzing... ' + data.remaining + ' left';
                // Continue with next batch after a short delay
                setTimeout(processBatch, 500);
            } else {
                showToast('All emails analyzed!', 'success');
                analysisRunning = false;
                btn.disabled = false;
                btn.style.display = 'none';
                loadInbox(inboxCurrentPage);
            }
        } catch (e) {
            showToast('Analysis error: ' + e.message, 'error');
            analysisRunning = false;
            btn.disabled = false;
            btn.querySelector('span').textContent = originalText;
        }
    }

    processBatch();
}
```

**Commit message:** `feat(email): background batch analysis with polling progress`

---

### Task 3: Sort Controls

Add a sort dropdown next to the search bar allowing sort by date, priority, sentiment, or unread-first. Backend already uses `ORDER BY received_at DESC` — extend with a `sort` query parameter.

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` — add `sort` parameter to `get_inbox`
- Modify: `platform_v2/templates/tools/email_manager.html` — add sort dropdown HTML + JS

**Backend — extend get_inbox with sort parameter:**

In the `get_inbox` route, after the `search` parameter parsing (~line 217), add:

```python
sort = request.args.get("sort", "date_desc")
```

Replace the hardcoded `ORDER BY received_at DESC` with:

```python
sort_map = {
    "date_desc": "received_at DESC",
    "date_asc": "received_at ASC",
    "priority_asc": "COALESCE(ai_priority, 99) ASC, received_at DESC",
    "unread_first": "is_read ASC, received_at DESC",
    "sentiment": "CASE ai_sentiment WHEN 'negative' THEN 1 WHEN 'mixed' THEN 2 WHEN 'neutral' THEN 3 WHEN 'positive' THEN 4 ELSE 5 END, received_at DESC",
}
order_clause = sort_map.get(sort, "received_at DESC")
```

Then use `ORDER BY {order_clause}` in the query.

**Frontend — add sort dropdown:**

In the `inbox-header-actions` div, add a select before the search group:

```html
<select id="inbox-sort-select" class="em-select em-select--compact" onchange="sortInbox()">
    <option value="date_desc">Newest First</option>
    <option value="date_asc">Oldest First</option>
    <option value="priority_asc">Highest Priority</option>
    <option value="unread_first">Unread First</option>
    <option value="sentiment">By Sentiment</option>
</select>
```

**Frontend — add JS:**

Add state variable `let inboxCurrentSort = 'date_desc';` alongside the other inbox state vars.

```javascript
function sortInbox() {
    inboxCurrentSort = document.getElementById('inbox-sort-select').value;
    loadInbox(1);
}
```

In `loadInbox()`, add the sort parameter to the URL params:

```javascript
if (inboxCurrentSort && inboxCurrentSort !== 'date_desc') params.set('sort', inboxCurrentSort);
```

**CSS for compact select:**

```css
.em-select--compact {
    padding: 6px 10px;
    font-size: 12px;
    min-width: 140px;
}
```

**Commit message:** `feat(email): add sort controls (date, priority, unread, sentiment)`

---

### Task 4: Bulk Actions

Add checkboxes to each email row, a "select all" checkbox in the header, and a bulk action bar that appears when emails are selected (Mark Read, Mark Unread, Archive, Analyze Selected).

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` — add `/api/inbox/bulk` endpoint
- Modify: `platform_v2/templates/tools/email_manager.html` — add checkboxes, bulk bar HTML, CSS, JS

**Backend — add bulk action endpoint:**

```python
@email_manager_bp.route("/api/inbox/bulk", methods=["POST"])
@login_required
def bulk_action():
    """Perform bulk actions on selected emails."""
    try:
        data = request.get_json(force=True)
        ids = data.get("ids", [])
        action = data.get("action")

        if not ids or not action:
            return jsonify({"success": False, "error": "Missing ids or action"}), 400

        if len(ids) > 200:
            return jsonify({"success": False, "error": "Max 200 emails per bulk action"}), 400

        valid_actions = ["mark_read", "mark_unread", "archive", "star", "unstar"]
        if action not in valid_actions:
            return jsonify({"success": False, "error": f"Invalid action: {action}"}), 400

        conn = get_db()
        cur = conn.cursor()

        placeholders = ",".join(["%s"] * len(ids))

        if action == "mark_read":
            cur.execute(f"UPDATE email_inbox SET is_read = TRUE WHERE id IN ({placeholders})", ids)
        elif action == "mark_unread":
            cur.execute(f"UPDATE email_inbox SET is_read = FALSE WHERE id IN ({placeholders})", ids)
        elif action == "archive":
            cur.execute(f"UPDATE email_inbox SET is_archived = TRUE WHERE id IN ({placeholders})", ids)
        elif action == "star":
            cur.execute(f"UPDATE email_inbox SET is_starred = TRUE WHERE id IN ({placeholders})", ids)
        elif action == "unstar":
            cur.execute(f"UPDATE email_inbox SET is_starred = FALSE WHERE id IN ({placeholders})", ids)

        affected = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "affected": affected})
    except Exception as e:
        logger.error(f"Bulk action failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

**Frontend — add checkbox to table header (line 177-185):**

Replace the star header `<th style="width: 40px;"></th>` with:

```html
<th style="width: 40px;">
    <input type="checkbox" id="inbox-select-all" onchange="toggleSelectAll(this.checked)" title="Select all">
</th>
<th style="width: 40px;"></th>
```

**Frontend — add checkbox to buildInboxRow():**

Insert a checkbox cell as the first cell in `buildInboxRow()`, before the star cell:

```javascript
// Checkbox cell
const tdCheck = document.createElement('td');
const checkbox = document.createElement('input');
checkbox.type = 'checkbox';
checkbox.className = 'inbox-row-checkbox';
checkbox.dataset.emailId = email.id;
checkbox.addEventListener('click', function(e) { e.stopPropagation(); updateBulkBar(); });
tdCheck.appendChild(checkbox);
tr.appendChild(tdCheck);
```

Update the header `colSpan` values from 7 to 8 everywhere they appear.

**Frontend — add bulk action bar HTML (after the stats bar):**

```html
<div class="inbox-bulk-bar" id="inbox-bulk-bar" style="display: none;">
    <span class="bulk-count" id="bulk-count">0 selected</span>
    <div class="bulk-actions">
        <button class="em-btn em-btn--sm em-btn--outline" onclick="bulkAction('mark_read')">
            <i data-lucide="eye"></i> Mark Read
        </button>
        <button class="em-btn em-btn--sm em-btn--outline" onclick="bulkAction('mark_unread')">
            <i data-lucide="eye-off"></i> Mark Unread
        </button>
        <button class="em-btn em-btn--sm em-btn--outline" onclick="bulkAction('archive')">
            <i data-lucide="archive"></i> Archive
        </button>
        <button class="em-btn em-btn--sm em-btn--outline" onclick="bulkAnalyzeSelected()">
            <i data-lucide="sparkles"></i> Analyze Selected
        </button>
        <button class="em-btn em-btn--sm em-btn--outline" onclick="clearSelection()">
            <i data-lucide="x"></i> Clear
        </button>
    </div>
</div>
```

**Frontend — add bulk JS:**

```javascript
function getSelectedIds() {
    return Array.from(document.querySelectorAll('.inbox-row-checkbox:checked'))
        .map(cb => parseInt(cb.dataset.emailId));
}

function updateBulkBar() {
    const ids = getSelectedIds();
    const bar = document.getElementById('inbox-bulk-bar');
    if (ids.length > 0) {
        bar.style.display = 'flex';
        document.getElementById('bulk-count').textContent = ids.length + ' selected';
    } else {
        bar.style.display = 'none';
    }
    // Update select-all checkbox state
    const allBoxes = document.querySelectorAll('.inbox-row-checkbox');
    const selectAll = document.getElementById('inbox-select-all');
    if (selectAll && allBoxes.length > 0) {
        selectAll.checked = ids.length === allBoxes.length;
        selectAll.indeterminate = ids.length > 0 && ids.length < allBoxes.length;
    }
}

function toggleSelectAll(checked) {
    document.querySelectorAll('.inbox-row-checkbox').forEach(cb => cb.checked = checked);
    updateBulkBar();
}

function clearSelection() {
    document.querySelectorAll('.inbox-row-checkbox').forEach(cb => cb.checked = false);
    document.getElementById('inbox-select-all').checked = false;
    updateBulkBar();
}

async function bulkAction(action) {
    const ids = getSelectedIds();
    if (!ids.length) return;

    try {
        const resp = await fetch('/tools/email-manager/api/inbox/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids, action })
        });
        const data = await resp.json();
        if (data.success) {
            showToast(action.replace('_', ' ') + ': ' + data.affected + ' emails', 'success');
            clearSelection();
            loadInbox(inboxCurrentPage);
            loadInboxStats();
        } else {
            showToast(data.error || 'Bulk action failed', 'error');
        }
    } catch (e) {
        showToast('Bulk action error', 'error');
    }
}

async function bulkAnalyzeSelected() {
    const ids = getSelectedIds();
    if (!ids.length) return;

    const btn = event.target.closest('button');
    btn.disabled = true;
    showToast('Analyzing ' + ids.length + ' emails...', 'info');

    let analyzed = 0;
    for (const id of ids) {
        try {
            await fetch('/tools/email-manager/api/inbox/' + id + '/analyze', { method: 'POST' });
            analyzed++;
        } catch (e) { /* continue */ }
    }

    showToast('Analyzed ' + analyzed + '/' + ids.length + ' emails', 'success');
    btn.disabled = false;
    clearSelection();
    loadInbox(inboxCurrentPage);
    loadInboxStats();
}
```

**CSS for bulk bar:**

```css
.inbox-bulk-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: rgba(255, 200, 0, 0.05);
    border: 1px solid rgba(255, 200, 0, 0.2);
    border-radius: 8px;
    margin-bottom: 8px;
}
.bulk-count {
    font-size: 13px;
    font-weight: 600;
    color: #FFC800;
}
.bulk-actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}
.inbox-row-checkbox {
    cursor: pointer;
    accent-color: #00FFFF;
}
```

**Commit message:** `feat(email): bulk actions — select, mark read/unread, archive, analyze`

---

### Task 5: Auto-Check Interval

Use the existing `check_interval_minutes` setting to auto-fetch new emails via a JS `setInterval`. Display the countdown in the stats bar.

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html` — add auto-check timer JS and countdown display

**Frontend — add auto-check HTML (in stats bar, after the analyze button):**

```html
<span class="inbox-auto-check" id="inbox-auto-check" style="display: none;">
    <i data-lucide="clock"></i>
    <span id="auto-check-countdown"></span>
</span>
```

**Frontend — add JS:**

```javascript
let autoCheckTimer = null;
let autoCheckSeconds = 0;
let autoCheckInterval = 300; // default 5 min, updated from settings

async function initAutoCheck() {
    try {
        const resp = await fetch('/tools/email-manager/api/imap/settings');
        const data = await resp.json();
        if (data.success && data.settings && data.settings.length > 0) {
            const interval = data.settings[0].check_interval_minutes || 5;
            autoCheckInterval = interval * 60;
            startAutoCheck();
        }
    } catch (e) {
        console.error('Auto-check init error:', e);
    }
}

function startAutoCheck() {
    stopAutoCheck();
    autoCheckSeconds = autoCheckInterval;
    const el = document.getElementById('inbox-auto-check');
    if (el) el.style.display = '';

    autoCheckTimer = setInterval(function() {
        autoCheckSeconds--;
        const countdownEl = document.getElementById('auto-check-countdown');
        if (countdownEl) {
            const min = Math.floor(autoCheckSeconds / 60);
            const sec = autoCheckSeconds % 60;
            countdownEl.textContent = min + ':' + (sec < 10 ? '0' : '') + sec;
        }

        if (autoCheckSeconds <= 0) {
            // Trigger check
            checkInboxNow();
            autoCheckSeconds = autoCheckInterval;
        }
    }, 1000);
}

function stopAutoCheck() {
    if (autoCheckTimer) {
        clearInterval(autoCheckTimer);
        autoCheckTimer = null;
    }
}
```

Call `initAutoCheck()` from `DOMContentLoaded`.

**CSS:**

```css
.inbox-auto-check {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: rgba(0, 255, 255, 0.5);
}
.inbox-auto-check i { width: 12px; height: 12px; }
```

**Commit message:** `feat(email): auto-check interval with countdown timer`

---

### Task 6: Unread Badge on Nav

Add an unread email count badge to the Email button in the business tools navigation bar. This requires passing the unread count from the Flask route to the template.

**Files:**
- Modify: `platform_v2/tools/email_manager/routes.py` — inject `email_unread_count` into template context
- Modify: `platform_v2/templates/includes/business_tools_nav.html` — add badge span + CSS + JS

**Backend — inject unread count:**

In the `index()` route of `routes.py`, add a query to get unread count and pass it to the template context. Find the existing `render_template` call and add the variable.

First, read `routes.py` to find the index route, then add:

```python
# Get unread inbox count for nav badge
try:
    cur.execute("SELECT COUNT(*) as c FROM email_inbox WHERE is_read = FALSE AND is_archived = FALSE")
    email_unread_count = cur.fetchone()["c"]
except Exception:
    email_unread_count = 0
```

Pass `email_unread_count=email_unread_count` to `render_template()`.

**Frontend — add badge to nav (business_tools_nav.html line 85-86):**

Replace the Email nav link content:

```html
<a href="{{ url_for('email_manager.index') }}"
   class="nav-module-btn {% if request.endpoint and 'email_manager' in request.endpoint %}active{% endif %}"
   onclick="showTransition(event, this.href)"
   title="Email Manager">
    <i data-lucide="mail"></i>
    <span>Email</span>
    {% if email_unread_count is defined and email_unread_count > 0 %}
    <span class="nav-badge">{{ email_unread_count if email_unread_count < 100 else '99+' }}</span>
    {% endif %}
</a>
```

**CSS (in business_tools_nav.html style block):**

```css
.nav-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    background: #FF4444;
    color: white;
    font-size: 10px;
    font-weight: 700;
    min-width: 16px;
    height: 16px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
    line-height: 1;
}
.nav-module-btn {
    position: relative;
}
```

Note: The `nav-module-btn` may already have `position: relative` — check existing CSS before adding. The badge needs the parent to be `position: relative`.

**Commit message:** `feat(email): unread badge on nav bar`

---

## Execution Notes

- **No new dependencies** — all features use existing Flask, psycopg2, vanilla JS
- **No new tables/migrations** — all features use existing `email_inbox` table
- **Template is large (~3200 lines)** — use line-specific edits, not full rewrites
- **LCARS theme** — use cyan (#00FFFF) for primary, gold (#FFC800) for warnings, pink (#FF69B4) for business nav accents
- **GPU safety** — batch analysis sleeps 1s between Ollama calls
- **Test each task** by restarting the container: `docker compose restart archie_platform`
