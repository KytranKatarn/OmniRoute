# DHQ System Alerts History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a paginated, filterable System Alerts History section to the DHQ Autonomy tab, backed by `system_notifications`.

**Architecture:** One API endpoint in `dispatch_routes.py`, one new IIFE JS file (`alerts-history.js`), and one HTML section inserted into `panel-autonomy`. Follows the exact pattern of Dispatch History (`dispatch-history.js` + `dispatch_routes.py`). All innerHTML calls pass strings through `_esc()` — same approach as existing `dispatch-history.js`.

**Tech Stack:** Flask (Python), vanilla JS (IIFE), PostgreSQL (`system_notifications` table, 19k rows), Jinja2 template.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `platform_v2/tools/department_hq/dispatch_routes.py` | Edit | Add `GET /api/alerts/history` endpoint |
| `platform_v2/static/js/alerts-history.js` | Create | Fetch, render, filter, paginate alerts |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Edit | HTML section + script tag + `ahInit()` call |

---

## Task 1: API Endpoint

**Files:**
- Modify: `platform_v2/tools/department_hq/dispatch_routes.py`

- [ ] **Step 1: Locate insertion point**

```bash
grep -n "def dispatch_history_agents\|def dispatch_history_capabilities" \
  platform_v2/tools/department_hq/dispatch_routes.py
```

Note the line number. The new function goes immediately before `dispatch_history_agents`.

- [ ] **Step 2: Insert the endpoint**

Add this block immediately before the `def dispatch_history_agents` function:

```python
    @bp.route("/api/alerts/history", methods=["GET"])
    @admin_required_decorator
    def alerts_history():
        """Paginated system_notifications with filter + stats."""
        now = now_utc()
        default_from = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        default_to = now.strftime("%Y-%m-%d")
        from_date = request.args.get("from_date", default_from)
        to_date = request.args.get("to_date", default_to)
        type_filter = request.args.get("type", "all").strip()
        priority_filter = request.args.get("priority", "all").strip()
        status_filter = request.args.get("status", "all").strip()
        q = request.args.get("q", "").strip()
        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            page = max(1, int(request.args.get("page", 1)))
        except (ValueError, TypeError):
            limit, page = 50, 1
        offset = (page - 1) * limit

        try:
            with get_db_cursor() as (conn, cur):
                conditions = [
                    "is_archived = false",
                    "created_at >= %(from_date)s::date",
                    "created_at < %(to_date)s::date + interval '1 day'",
                ]
                params = {"from_date": from_date, "to_date": to_date}

                if type_filter != "all":
                    conditions.append("type = %(type_filter)s")
                    params["type_filter"] = type_filter
                if priority_filter != "all":
                    conditions.append("priority = %(priority_filter)s")
                    params["priority_filter"] = priority_filter
                if status_filter == "unread":
                    conditions.append("is_read = false")
                elif status_filter == "read":
                    conditions.append("is_read = true")
                if q:
                    conditions.append(
                        "(title ILIKE %(q_like)s OR message ILIKE %(q_like)s"
                        " OR source ILIKE %(q_like)s)"
                    )
                    params["q_like"] = f"%{q}%"

                where = " AND ".join(conditions)

                # Windowed stats (respects active filters)
                cur.execute(
                    f"""
                    SELECT COUNT(*)::int AS total,
                           SUM(CASE WHEN is_read = false THEN 1 ELSE 0 END)::int AS unread
                    FROM system_notifications WHERE {where}
                    """,
                    params,
                )
                stat_row = cur.fetchone()
                total = int(stat_row["total"] or 0)
                unread = int(stat_row["unread"] or 0)

                # Fixed 24h error/warning counts (always full 24h, ignores date filter)
                cutoff_24h = now - timedelta(hours=24)
                cur.execute(
                    """
                    SELECT
                        SUM(CASE WHEN type = 'error'   THEN 1 ELSE 0 END)::int AS errors_24h,
                        SUM(CASE WHEN type = 'warning' THEN 1 ELSE 0 END)::int AS warnings_24h
                    FROM system_notifications
                    WHERE is_archived = false AND created_at >= %(cutoff)s
                    """,
                    {"cutoff": cutoff_24h},
                )
                sr = cur.fetchone()

                # Paginated rows
                cur.execute(
                    f"""
                    SELECT id, type, priority, title, message, source, source_icon,
                           is_read, telegram_forwarded, grouped_count, related_action,
                           metadata, created_at
                    FROM system_notifications
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT %(limit)s OFFSET %(offset)s
                    """,
                    {**params, "limit": limit, "offset": offset},
                )
                cols = [
                    "id", "type", "priority", "title", "message", "source",
                    "source_icon", "is_read", "telegram_forwarded", "grouped_count",
                    "related_action", "metadata", "created_at",
                ]
                rows = []
                for r in cur.fetchall():
                    row_dict = dict(zip(cols, r)) if not hasattr(r, "keys") else dict(r)
                    if row_dict.get("created_at"):
                        row_dict["created_at"] = row_dict["created_at"].isoformat()
                    rows.append(row_dict)

                pages = max(1, (total + limit - 1) // limit)
                return jsonify(
                    {
                        "stats": {
                            "total": total,
                            "unread": unread,
                            "errors_24h": int(sr["errors_24h"] or 0),
                            "warnings_24h": int(sr["warnings_24h"] or 0),
                        },
                        "rows": rows,
                        "page": page,
                        "pages": pages,
                        "total": total,
                    }
                )
        except Exception:
            logger.exception("[Dispatch] alerts_history failed")
            return jsonify({"error": "internal error"}), 500
```

- [ ] **Step 3: Smoke-test the route is registered**

```bash
docker compose restart archie_platform
sleep 10
docker logs archie_platform 2>&1 | grep -i "alerts.history\|error" | tail -5
```

Expected: no import errors. Then visit `http://192.168.1.200:3000/tools/department-hq/api/alerts/history?limit=2` in a logged-in browser — should return `{"stats": {...}, "rows": [...], "page": 1, ...}`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/dispatch_routes.py
git commit -m "feat(dhq): add GET /api/alerts/history endpoint over system_notifications"
```

---

## Task 2: alerts-history.js

**Security note:** All DB-sourced strings are passed through `_esc()` before any innerHTML assignment. Pattern matches existing `dispatch-history.js`.

**Files:**
- Create: `platform_v2/static/js/alerts-history.js`

- [ ] **Step 1: Create the file**

```bash
touch platform_v2/static/js/alerts-history.js
```

- [ ] **Step 2: Write the IIFE**

Open `platform_v2/static/js/alerts-history.js` and write this content:

```
/* alerts-history.js — fetch, render, filter, paginate DHQ System Alerts History */
/* All innerHTML calls pass content through _esc() — same pattern as dispatch-history.js */
(function () {
  'use strict';

  var BASE = '/tools/department-hq/api/alerts/history';
  var _page = 1;
  var _debounceTimer = null;

  var TYPE_COLORS = {
    error:   '#ef4444',
    warning: '#f59e0b',
    alert:   '#f97316',
    info:    '#00e5ff',
    success: '#10b981'
  };

  /* Public API */

  window.ahFetch = function (resetPage) {
    if (resetPage) _page = 1;
    fetch(BASE + '?' + _params())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _renderStats(data.stats || {});
        _renderTable(data.rows || []);
        _renderPagination(data.page, data.pages, data.total);
      })
      .catch(function (err) { console.error('Alerts history fetch failed', err); });
  };

  window.ahPage = function (delta) {
    _page = Math.max(1, _page + delta);
    window.ahFetch();
  };

  window.ahReset = function () {
    document.getElementById('ahFilterType').value = 'all';
    document.getElementById('ahFilterPriority').value = 'all';
    document.getElementById('ahFilterStatus').value = 'all';
    document.getElementById('ahFilterQ').value = '';
    _setDefaultDates();
    window.ahFetch(true);
  };

  window.ahDebounce = function () {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(function () { window.ahFetch(true); }, 400);
  };

  window.ahToggleRow = function (id) {
    var detail = document.getElementById('ah-detail-' + id);
    var row = document.getElementById('ah-row-' + id);
    if (!detail || !row) return;
    var hidden = detail.style.display === 'none' || detail.style.display === '';
    detail.style.display = hidden ? 'table-row' : 'none';
    row.style.opacity = hidden ? '0.8' : '1';
  };

  window.ahInit = function () {
    if (window._ahInitDone) return;
    window._ahInitDone = true;
    _setDefaultDates();
    window.ahFetch(true);
  };

  /* Private */

  function _params() {
    var p = new URLSearchParams();
    p.set('type',      _val('ahFilterType'));
    p.set('priority',  _val('ahFilterPriority'));
    p.set('status',    _val('ahFilterStatus'));
    p.set('from_date', _val('ahFilterFrom'));
    p.set('to_date',   _val('ahFilterTo'));
    p.set('q',         _val('ahFilterQ'));
    p.set('page', _page);
    return p.toString();
  }

  function _val(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function _renderStats(s) {
    var el = document.getElementById('ahStats');
    if (!el) return;
    el.innerHTML =
      _chip('TOTAL',      s.total        || 0, '#00e5ff') + ' ' +
      _chip('UNREAD',     s.unread       || 0, '#f59e0b') + ' ' +
      _chip('ERRORS 24H', s.errors_24h   || 0, '#ef4444') + ' ' +
      _chip('WARN 24H',   s.warnings_24h || 0, '#f97316');
    var badge = document.getElementById('ahTotalBadge');
    if (badge) badge.textContent = '(' + (s.total || 0) + ')';
  }

  function _chip(label, value, color) {
    return '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;' +
      'padding:3px 8px;border-radius:3px;background:rgba(0,0,0,0.3);' +
      'border:1px solid ' + color + '40;display:inline-block;">' +
      '<span style="color:' + color + ';font-weight:600;">' + Number(value) + '</span>' +
      ' <span style="color:var(--dhq-text-dim);letter-spacing:1px;">' + label + '</span>' +
      '</span>';
  }

  function _renderTable(rows) {
    var tbody = document.getElementById('ahTableBody');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:16px;text-align:center;' +
        'color:var(--dhq-text-dim);font-size:0.78rem;">No alerts in this range</td></tr>';
      return;
    }
    var html = '';
    rows.forEach(function (r) {
      var ts = r.created_at ? _esc(r.created_at.replace('T', ' ').slice(0, 16)) : '—';
      var dot = !r.is_read
        ? '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;' +
          'background:#00e5ff;margin-right:5px;vertical-align:middle;"></span>'
        : '';
      html +=
        '<tr id="ah-row-' + Number(r.id) + '" onclick="ahToggleRow(' + Number(r.id) + ')" ' +
        'style="cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.05);" ' +
        'onmouseover="this.style.background=\'rgba(0,229,255,0.03)\'" ' +
        'onmouseout="this.style.background=\'\'">' +
        '<td style="padding:6px 8px;white-space:nowrap;color:var(--dhq-text-dim);' +
          'font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;">' + ts + '</td>' +
        '<td style="padding:6px 8px;font-size:0.72rem;">' +
          _esc(r.source_icon || '📋') + ' ' + _esc(r.source || '') + '</td>' +
        '<td style="padding:6px 8px;">' + _typeBadge(r.type) + '</td>' +
        '<td style="padding:6px 8px;">' + _priorityBadge(r.priority) + '</td>' +
        '<td style="padding:6px 8px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
          dot + _esc(r.title || r.message || '') + '</td>' +
        '<td style="padding:6px 8px;text-align:center;font-size:0.75rem;">' +
          (r.telegram_forwarded ? '<span title="Telegram forwarded" style="opacity:0.5;">&#x2708;</span>' : '') +
        '</td></tr>' +
        '<tr id="ah-detail-' + Number(r.id) + '" style="display:none;background:rgba(0,0,0,0.2);">' +
        '<td colspan="6" style="padding:8px 14px;">' + _renderDetail(r) + '</td></tr>';
    });
    tbody.innerHTML = html;
  }

  function _renderDetail(r) {
    var parts = [];
    if (r.message && r.message !== r.title) {
      parts.push('<div style="font-size:0.78rem;margin-bottom:6px;line-height:1.4;">' +
        _esc(r.message) + '</div>');
    }
    if (r.related_action) {
      parts.push('<div style="font-size:0.7rem;color:var(--dhq-text-dim);">Action: ' +
        _esc(r.related_action) + '</div>');
    }
    if (r.grouped_count && r.grouped_count > 1) {
      parts.push('<div style="font-size:0.7rem;color:var(--dhq-text-dim);">Grouped: ' +
        Number(r.grouped_count) + ' events</div>');
    }
    if (r.metadata && typeof r.metadata === 'object' && Object.keys(r.metadata).length) {
      parts.push('<pre style="font-size:0.65rem;color:var(--dhq-text-dim);margin:4px 0;' +
        'white-space:pre-wrap;word-break:break-all;">' +
        _esc(JSON.stringify(r.metadata, null, 2)) + '</pre>');
    }
    return parts.length
      ? parts.join('')
      : '<span style="color:var(--dhq-text-dim);font-size:0.75rem;">No additional details</span>';
  }

  function _renderPagination(page, pages, total) {
    var el = document.getElementById('ahPagination');
    if (!el) return;
    if (!pages || pages <= 1) { el.innerHTML = ''; return; }
    var btnStyle = 'background:none;border:1px solid rgba(255,255,255,0.2);' +
      'color:var(--dhq-text-dim);padding:2px 10px;border-radius:3px;cursor:pointer;';
    el.innerHTML =
      '<button onclick="ahPage(-1)" ' + (page <= 1 ? 'disabled' : '') +
        ' style="' + btnStyle + '">&#9664;</button>' +
      '<span style="color:var(--dhq-text-dim);font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;">' +
        'Page ' + Number(page) + ' / ' + Number(pages) + ' — ' + Number(total) + ' total</span>' +
      '<button onclick="ahPage(1)" ' + (page >= pages ? 'disabled' : '') +
        ' style="' + btnStyle + '">&#9654;</button>';
  }

  function _typeBadge(type) {
    var safeType = _esc((type || '').toUpperCase());
    var color = TYPE_COLORS[type] || '#888888';
    return '<span style="font-size:0.65rem;font-family:\'IBM Plex Mono\',monospace;' +
      'padding:1px 6px;border-radius:3px;background:' + color + '22;color:' + color + ';' +
      'border:1px solid ' + color + '44;letter-spacing:1px;">' + safeType + '</span>';
  }

  function _priorityBadge(priority) {
    if (!priority || priority === 'normal') return '';
    var safePriority = _esc(priority.toUpperCase());
    var color = priority === 'critical' ? '#ef4444' : '#f97316';
    return '<span style="font-size:0.6rem;font-family:\'IBM Plex Mono\',monospace;' +
      'padding:1px 5px;border-radius:3px;background:' + color + '22;color:' + color + ';' +
      'border:1px solid ' + color + '44;letter-spacing:1px;margin-left:4px;">' +
      safePriority + '</span>';
  }

  function _setDefaultDates() {
    var now = new Date();
    var toEl  = document.getElementById('ahFilterTo');
    var fromEl = document.getElementById('ahFilterFrom');
    if (toEl)   toEl.value   = now.toISOString().slice(0, 10);
    if (fromEl) fromEl.value = new Date(now - 7 * 86400000).toISOString().slice(0, 10);
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

}());
```

- [ ] **Step 3: Lint check**

```bash
node --check platform_v2/static/js/alerts-history.js && echo "SYNTAX OK"
```

Expected: `SYNTAX OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/alerts-history.js
git commit -m "feat(dhq): add alerts-history.js IIFE for System Alerts History"
```

---

## Task 3: HTML Integration

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

Three edits: (A) HTML section in Autonomy tab, (B) script tag, (C) `ahInit()` in tab-switch handler.

- [ ] **Step 1: Find exact insertion points**

```bash
grep -n "JOBS BY DEPARTMENT\|END AUTONOMY TAB\|dispatch-history.js\|dhInit\|switchTab" \
  platform_v2/tools/department_hq/templates/department_hq.html | head -20
```

Note line numbers for:
1. `<!-- END AUTONOMY TAB PANEL -->` — insert HTML **before** this line
2. `dispatch-history.js` script tag — add new script tag **after** this line
3. Line containing `dhInit()` — add `ahInit()` call in the same tab-switch block for `autonomy`

- [ ] **Step 2: Insert HTML section (Edit A)**

Find `<!-- END AUTONOMY TAB PANEL -->`. Insert immediately before it:

```html
      <!-- System Alerts History -->
      <div class="dhq-dispatch-section" id="alerts-history-section" style="margin-top:1.5rem;">
        <div class="dhq-section-title">
          SYSTEM ALERTS HISTORY
          <span id="ahTotalBadge" style="color:var(--dhq-text-dim);font-family:'IBM Plex Mono',monospace;font-size:0.7rem;margin-left:8px;"></span>
          <button onclick="ahReset()" style="float:right;background:none;border:1px solid rgba(255,255,255,0.2);color:var(--dhq-text-dim);padding:2px 8px;border-radius:4px;font-size:0.65rem;cursor:pointer;letter-spacing:1px;">&#8634; RESET</button>
        </div>
        <div id="ahStats" style="display:flex;gap:8px;flex-wrap:wrap;padding:8px 0;"></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:center;">
          <select id="ahFilterType" onchange="ahFetch(true)" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 6px;border-radius:3px;font-size:0.72rem;">
            <option value="all">All Types</option>
            <option value="error">Error</option>
            <option value="warning">Warning</option>
            <option value="alert">Alert</option>
            <option value="info">Info</option>
            <option value="success">Success</option>
          </select>
          <select id="ahFilterPriority" onchange="ahFetch(true)" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 6px;border-radius:3px;font-size:0.72rem;">
            <option value="all">All Priority</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
          </select>
          <select id="ahFilterStatus" onchange="ahFetch(true)" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 6px;border-radius:3px;font-size:0.72rem;">
            <option value="all">All Status</option>
            <option value="unread">Unread</option>
            <option value="read">Read</option>
          </select>
          <input id="ahFilterFrom" type="date" onchange="ahFetch(true)" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 6px;border-radius:3px;font-size:0.72rem;">
          <input id="ahFilterTo" type="date" onchange="ahFetch(true)" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 6px;border-radius:3px;font-size:0.72rem;">
          <input id="ahFilterQ" type="text" placeholder="Search alerts..." oninput="ahDebounce()" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text);padding:3px 8px;border-radius:3px;font-size:0.72rem;min-width:160px;">
        </div>
        <div style="overflow-x:auto;">
          <table style="width:100%;font-size:0.78rem;border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--dhq-text-dim);font-family:'IBM Plex Mono',monospace;font-size:0.65rem;letter-spacing:1px;">
                <th style="padding:4px 8px;text-align:left;font-weight:400;">TIME</th>
                <th style="padding:4px 8px;text-align:left;font-weight:400;">SOURCE</th>
                <th style="padding:4px 8px;text-align:left;font-weight:400;">TYPE</th>
                <th style="padding:4px 8px;text-align:left;font-weight:400;">PRIORITY</th>
                <th style="padding:4px 8px;text-align:left;font-weight:400;">TITLE</th>
                <th style="padding:4px 8px;text-align:center;font-weight:400;">TG</th>
              </tr>
            </thead>
            <tbody id="ahTableBody">
              <tr><td colspan="6" style="padding:16px;text-align:center;color:var(--dhq-text-dim);font-size:0.78rem;">Loading...</td></tr>
            </tbody>
          </table>
        </div>
        <div id="ahPagination" style="display:flex;align-items:center;gap:12px;padding:8px 0;font-size:0.75rem;"></div>
      </div>
```

- [ ] **Step 3: Add script tag (Edit B)**

Find the line containing `dispatch-history.js`. Add immediately after it:

```html
<script src="{{ url_for('static', filename='js/alerts-history.js') }}"></script>
```

- [ ] **Step 4: Wire ahInit() into tab switch (Edit C)**

Find the line containing `dhInit()`. It will be inside a tab-switch handler tied to `'dispatch'`. Immediately after that block, add an equivalent block for `'autonomy'`. Example — if the existing code looks like:

```javascript
if (tab === 'dispatch') { if (!window._dhInitDone) dhInit(); }
```

Add:

```javascript
if (tab === 'autonomy') { if (!window._ahInitDone) ahInit(); }
```

If it's a switch statement with `case 'dispatch': dhInit(); break;`, add:

```javascript
case 'autonomy':
  if (!window._ahInitDone) ahInit();
  break;
```

- [ ] **Step 5: Deploy and browser-verify**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/department-hq` → Autonomy tab → scroll to SYSTEM ALERTS HISTORY.

Verify each item:
1. Stats bar appears with 4 chips — TOTAL should be ~19,293
2. Table loads rows with color-coded type badges (red=error, amber=warning, cyan=info)
3. Select `type=error` in dropdown → only red badges remain
4. Select `status=unread` → row count reduces
5. Type `dispatch` in search → results filter after ~400ms pause
6. Click any row → detail panel expands below it
7. Click RESET button → filters clear, 7-day default range restores
8. Use page ▶ button → page 2 loads correctly

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): wire System Alerts History section into Autonomy tab"
```

---

## Task 4: PR

- [ ] **Open PR**

```bash
git push origin HEAD
gh pr create \
  --title "feat(dhq): System Alerts History in Autonomy tab" \
  --body "$(cat <<'EOF'
## Summary
- New SYSTEM ALERTS HISTORY section in DHQ Autonomy tab
- Follows dispatch-history.js pattern exactly: IIFE JS + API route + HTML section
- Queries system_notifications (19k rows) with filters: type / priority / status / date / search
- Stats bar: Total · Unread · Errors 24h · Warnings 24h
- Paginated 50/page, expandable rows show message + metadata + grouped_count

## Test plan
- [ ] Autonomy tab loads with SYSTEM ALERTS HISTORY section visible
- [ ] Stats chips show real numbers (~19k total)
- [ ] Type filter shows only matching badges
- [ ] Unread filter reduces count
- [ ] Search debounces at 400ms
- [ ] Row expand shows detail/metadata
- [ ] Pagination prev/next works
- [ ] Reset clears all filters and restores 7-day range

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Autonomy tab placement: Task 3 HTML ✅
- API filters (type, priority, status, q, from_date, to_date, page, limit): Task 1 Step 2 ✅
- Response shape (stats + rows + page + pages + total): Task 1 Step 2 ✅
- Stats: total, unread, errors_24h, warnings_24h: Task 1 Step 2 ✅
- `is_archived = false` always applied: Task 1 WHERE clause ✅
- JS public API (ahFetch/ahPage/ahReset/ahDebounce/ahInit/ahToggleRow): Task 2 ✅
- Type badge colors match spec: Task 2 `TYPE_COLORS` object ✅
- Expandable detail rows: Task 2 `_renderDetail()` ✅
- Pagination: Task 2 `_renderPagination()` ✅
- Out-of-scope items not implemented ✅

**Placeholder scan:** No TBD, no TODO, no "similar to", no incomplete code.

**Type consistency:** Element IDs (`ahFilterType`, `ahFilterPriority`, `ahFilterStatus`, `ahFilterFrom`, `ahFilterTo`, `ahFilterQ`, `ahTableBody`, `ahStats`, `ahTotalBadge`, `ahPagination`) defined in Task 3 HTML and read in Task 2 `_val()` / direct getElementById calls — all consistent.
