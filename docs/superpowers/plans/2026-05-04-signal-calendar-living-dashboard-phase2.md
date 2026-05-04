# SIGNAL Calendar Living Dashboard — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static theme-grid in DHQ → S.I.G.N.A.L. → Calendar with a 7-day chip-grid that renders the actual lifecycle state of every LinkedIn post (drafted → pending → executing → posted | failed | rejected | deferred) by consuming the new `GET /api/signal/calendar/live` endpoint shipped in Phase 1.

**Architecture:** Pure frontend change in `platform_v2/tools/department_hq/static/js/department-hq.js`. Replace the body of `renderSignalCalendar(el)` so it fetches `/api/signal/calendar/live?account=<signalAccount>` instead of the legacy `/api/signal/calendar`, and render each day-cell as 0–2 chips (one per language) with status-keyed colors and icons per the design spec. Chip click handlers are wired but stubbed — Phase 3 fills in the modal. Drop the calendar tab's TTL from 300s to 30s so polling reflects the design's "living dashboard" cadence.

**Tech Stack:** Vanilla JS in single-file convention (no module system, no build step). Inline styles on rendered HTML strings — matches existing renderer patterns. Visual verification via Playwright. No JS test harness exists in this repo, so verification is browser-rendered + DB fixture-driven.

**Spec:** `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md`
**Phase 1 plan (reference):** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify (lines ~1463 + ~1933) | Drop calendar TTL to 30s; rewrite `renderSignalCalendar` to consume `/api/signal/calendar/live`; add `_SIGNAL_STATUS_VISUALS` constant + `_renderSignalChip` + `_renderSignalDayCell` helpers; stub `_onSignalChipClick` for Phase 3 |
| `platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql` | Create | DB fixture inserting one approval row per status (posted/pending/executing/failed/rejected) for visual verification |
| (no new tests in py — existing Phase 1 tests cover the endpoint, frontend has no JS runner) | — | — |

The design intentionally keeps Phase 2 narrowly scoped: render-only. Modal lives in Phase 3, action endpoints in Phase 4, polling integration tweaks in Phase 5.

---

## Status → Visual Mapping (locked-in for this phase)

| status | bg | icon | label | clickable |
|---|---|---|---|---|
| `posted` | `#22c55e` | ✓ | POSTED | yes (no-op stub) |
| `pending` | `#f59e0b` | ⏳ | PENDING | yes (no-op stub) |
| `executing` | `#3b82f6` | ⟳ | EXECUTING | yes (no-op stub) |
| `failed` | `#ef4444` | ✗ | FAILED | yes (no-op stub) |
| `rejected` | `#9ca3af` | 🚫 | REJECTED | yes (no-op stub) |
| `deferred` | `#8b5cf6` | ⏸ | DEFERRED | yes (no-op stub) |

Language emoji: `🇨🇦` for EN, `⚜️` for FR (matches existing Telegram convention).
Today highlighted with `border:1px solid #22d3ee` and `box-shadow:0 0 8px rgba(34,211,238,0.3)`.

---

### Task 1: Drop calendar TTL to 30s

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js:1463`

**Why:** Design spec §7 sets 30s as the "living dashboard" polling cadence. Existing TTL is 300s (5min) — left over from the static theme grid where stale data was harmless.

- [ ] **Step 1: Make the change**

Find this line in `department-hq.js` (currently line 1463):
```javascript
var _signalTabTTL = { overview: 30, postlog: 60, pending: 15, hashtags: 120, calendar: 300, themes: 600 };
```

Change `calendar: 300` to `calendar: 30`:
```javascript
var _signalTabTTL = { overview: 30, postlog: 60, pending: 15, hashtags: 120, calendar: 30, themes: 600 };
```

- [ ] **Step 2: Verify the change**

Run:
```bash
grep -n "_signalTabTTL = " /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js
```
Expected: line shows `calendar: 30`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(signal-calendar): drop calendar tab TTL to 30s for living dashboard polling"
```

---

### Task 2: Add status-visuals constant and chip helper

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js` — insert above `renderSignalCalendar` (currently line 1933)

**Why:** Centralize the status → color/icon map so chip rendering is data-driven. A single helper `_renderSignalChip(post)` keeps the day-cell renderer simple in Task 3.

- [ ] **Step 1: Insert the visuals constant**

Above the `async function renderSignalCalendar(el) {` line (currently line 1933), add:

```javascript
// Phase 2: status -> chip visual map. Aligned with services/signal_post_status.py classifier.
var _SIGNAL_STATUS_VISUALS = {
    posted:    { bg:'#22c55e', fg:'#04130a', icon:'✓',  label:'POSTED'    },
    pending:   { bg:'#f59e0b', fg:'#1a0f00', icon:'⏳', label:'PENDING'   },
    executing: { bg:'#3b82f6', fg:'#04101f', icon:'⟳',  label:'EXECUTING' },
    failed:    { bg:'#ef4444', fg:'#1a0404', icon:'✗',  label:'FAILED'    },
    rejected:  { bg:'#9ca3af', fg:'#0d0f12', icon:'🚫', label:'REJECTED'  },
    deferred:  { bg:'#8b5cf6', fg:'#0a041a', icon:'⏸', label:'DEFERRED'  }
};

var _SIGNAL_LANG_EMOJI = { en: '🇨🇦', fr: '⚜️' };

// Phase 3 will replace this stub with the modal opener.
function _onSignalChipClick(approvalId, status) {
    console.log('[SIGNAL chip click]', { approvalId: approvalId, status: status });
    // Phase 3: openSignalPostModal(approvalId);
}

function _renderSignalChip(post) {
    var v = _SIGNAL_STATUS_VISUALS[post.status] || _SIGNAL_STATUS_VISUALS.failed;
    var langEmoji = _SIGNAL_LANG_EMOJI[post.lang] || '🌐';
    var pulseAnim = post.status === 'executing'
        ? 'animation:bmLightPulse 1.4s ease-in-out infinite;'
        : '';
    return '<button type="button" class="signal-chip"'
        + ' onclick="_onSignalChipClick(' + JSON.stringify(post.approval_id) + ',\'' + post.status + '\')"'
        + ' title="' + esc(v.label + ' — click for details (Phase 3)') + '"'
        + ' style="display:flex;align-items:center;gap:4px;width:100%;'
        +         'background:' + v.bg + ';color:' + v.fg + ';'
        +         'border:none;border-radius:4px;padding:4px 6px;margin-bottom:3px;'
        +         'font-family:\'IBM Plex Mono\',monospace;font-size:0.5rem;letter-spacing:0.5px;'
        +         'cursor:pointer;text-align:left;' + pulseAnim + '">'
        +     '<span style="font-size:0.65rem;">' + langEmoji + '</span>'
        +     '<span style="font-weight:700;">' + v.icon + '</span>'
        +     '<span style="flex:1;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        +         esc(v.label)
        +     '</span>'
        + '</button>';
}
```

- [ ] **Step 2: Sanity-check syntax**

Run:
```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK` (no syntax error).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(signal-calendar): add status-visuals constant + chip helper for Phase 2 grid"
```

---

### Task 3: Rewrite renderSignalCalendar to use live endpoint

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js:1933-1965`

**Why:** The existing renderer fetches `/api/signal/calendar` (theme schedule) and shows static slots. Phase 1 shipped the live endpoint and service. This task swaps the fetch URL and the renderer body.

- [ ] **Step 1: Replace the function body**

Replace the entire `renderSignalCalendar` function (currently lines 1933–1965) with:

```javascript
async function renderSignalCalendar(el) {
    var account = signalAccount || 'company';
    var data;
    try {
        data = await api('/api/signal/calendar/live?account=' + encodeURIComponent(account));
    } catch (err) {
        setHtml(el, '<div class="dhq-empty" style="color:#ef4444;">Calendar load failed: '
            + esc(err && err.message ? err.message : String(err)) + '</div>');
        return;
    }

    var days = data.days || [];
    var DAY_ABBR = ['MON','TUE','WED','THU','FRI','SAT','SUN'];

    var weekStart = data.week_start || '';
    var headerLine = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
        +     '<div style="color:#555;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">'
        +         'Living Dashboard — Week of ' + esc(weekStart) + ' · Account: ' + esc(account)
        +     '</div>'
        +     '<div style="color:#22d3ee;font-size:0.55rem;letter-spacing:1px;">'
        +         '⟳ polling every 30s'
        +     '</div>'
        + '</div>';

    var grid = '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px;">';
    for (var i = 0; i < 7; i++) {
        grid += _renderSignalDayCell(days[i] || { date:'', is_today:false, posts:[] }, DAY_ABBR[i]);
    }
    grid += '</div>';

    var legend = _renderSignalLegend();

    setHtml(el, headerLine + grid + legend);
}

function _renderSignalDayCell(day, abbr) {
    var posts = day.posts || [];
    var isToday = !!day.is_today;
    var border = isToday ? '#22d3ee' : '#333';
    var glow = isToday ? 'box-shadow:0 0 8px rgba(34,211,238,0.3);' : '';
    var dateLabel = (day.date || '').substring(5); // MM-DD

    var html = '<div style="background:#0d1117;border:1px solid ' + border + ';border-radius:5px;'
        +         'padding:7px;min-height:120px;display:flex;flex-direction:column;' + glow + '">'
        +     '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">'
        +         '<span style="font-size:0.55rem;color:' + border + ';font-family:\'Orbitron\',sans-serif;letter-spacing:1px;">'
        +             abbr + (isToday ? ' • TODAY' : '')
        +         '</span>'
        +         '<span style="font-size:0.45rem;color:#555;">' + esc(dateLabel) + '</span>'
        +     '</div>';

    if (!posts.length) {
        // No posts for this day — show a single ghost slot. Phase 4 wires the action.
        html += '<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            +         'border:1px dashed #2a2a2a;border-radius:4px;color:#444;'
            +         'font-size:0.5rem;font-style:italic;">+ Draft now</div>';
    } else {
        for (var p = 0; p < posts.length; p++) {
            html += _renderSignalChip(posts[p]);
        }
    }

    html += '</div>';
    return html;
}

function _renderSignalLegend() {
    var keys = ['posted','pending','executing','failed','rejected','deferred'];
    var items = '';
    for (var i = 0; i < keys.length; i++) {
        var v = _SIGNAL_STATUS_VISUALS[keys[i]];
        items += '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;'
            +              'font-size:0.5rem;color:#777;letter-spacing:1px;">'
            +     '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + v.bg + ';"></span>'
            +     v.label
            + '</span>';
    }
    return '<div style="margin-top:12px;padding-top:8px;border-top:1px solid #1a1a1a;">' + items + '</div>';
}
```

- [ ] **Step 2: Sanity-check syntax**

Run:
```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Restart platform to pick up new JS (static asset cache)**

Run:
```bash
docker compose restart archie_platform
```
Expected: `Container archie_platform Started`.

- [ ] **Step 4: Confirm endpoint still healthy after restart**

Run:
```bash
sleep 6 && curl -sS -o /dev/null -w "calendar/live: %{http_code}\n" "http://192.168.1.200:3000/tools/department-hq/api/signal/calendar/live?account=company"
```
Expected: `401` (auth-gated; route registered) — same as post-merge verification this morning.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(signal-calendar): replace theme-grid with live chip-grid (Phase 2)"
```

---

### Task 4: DB fixture for visual verification

**Files:**
- Create: `platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql`

**Why:** Phase 2 is a render-only change. The cheapest way to verify all 6 chip states render correctly is to seed `autonomy_approval_queue` with one row per status across this week's days, then visually inspect the calendar. Fixture is idempotent and cleanable.

- [ ] **Step 1: Write the fixture SQL**

Create `platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql`:

```sql
-- SIGNAL Calendar Phase 2 visual verification fixture.
-- Seeds one autonomy_approval_queue row per status for account='company'
-- spread across the current week. Idempotent — uses fixed reason markers so
-- DELETE-by-marker can clean up before re-insert.

BEGIN;

-- Clean any prior fixture rows
DELETE FROM autonomy_approval_queue
 WHERE reason LIKE '[PHASE2_FIXTURE]%';

-- 1. POSTED (Monday this week, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, executed_at, execution_result, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] posted EN sample content"}'::jsonb,
     'executed',
     '[PHASE2_FIXTURE] posted EN',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours 5 min',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours 10 min',
     '{"success":true,"_status":"posted"}'::jsonb,
     9001);

-- 2. PENDING (today, FR)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"fr","content":"[PHASE2_FIXTURE] ⚜️ pending FR contenu test"}'::jsonb,
     'pending',
     '[PHASE2_FIXTURE] pending FR ⚜️',
     CURRENT_DATE + interval '9 hours',
     9002);

-- 3. EXECUTING (today, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] executing EN sample"}'::jsonb,
     'approved',
     '[PHASE2_FIXTURE] executing EN',
     CURRENT_DATE + interval '8 hours',
     CURRENT_DATE + interval '8 hours 5 min',
     9003);

-- 4. FAILED (yesterday, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, executed_at, execution_result, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] failed EN sample"}'::jsonb,
     'executed',
     '[PHASE2_FIXTURE] failed EN',
     CURRENT_DATE - interval '1 day' + interval '9 hours',
     CURRENT_DATE - interval '1 day' + interval '9 hours 5 min',
     CURRENT_DATE - interval '1 day' + interval '9 hours 6 min',
     '{"success":false,"error":"Could not find Start a post button"}'::jsonb,
     9004);

-- 5. REJECTED (Wednesday this week, FR)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"fr","content":"[PHASE2_FIXTURE] ⚜️ rejected FR contenu"}'::jsonb,
     'rejected',
     '[PHASE2_FIXTURE] rejected FR ⚜️',
     date_trunc('week', CURRENT_DATE) + interval '2 day' + interval '10 hours',
     9005);

-- (deferred state from Layer A Phase 4 — skip for now; design notes deferred is post-v1)

COMMIT;

-- Verify
SELECT id, status, reason, created_at::date AS d
  FROM autonomy_approval_queue
 WHERE reason LIKE '[PHASE2_FIXTURE]%'
 ORDER BY created_at;
```

- [ ] **Step 2: Apply the fixture to live DB**

Run:
```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
```
Expected: `BEGIN`, 5 `INSERT 0 1` lines, `COMMIT`, then a SELECT showing 5 rows.

- [ ] **Step 3: Hit the live endpoint to confirm fixture flows through**

Run:
```bash
curl -sS "http://192.168.1.200:3000/tools/department-hq/api/signal/calendar/live?account=company" \
    -H "Cookie: $(cat /tmp/archie_admin_cookie 2>/dev/null || echo '')" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps([{'date':x['date'],'n':len(x['posts']),'st':[p['status'] for p in x['posts']]} for x in d.get('days',[])], indent=2))"
```

If the `Cookie` header is empty or you get `{"error":"unauthorized"}`, run the visual verification step (Task 5) instead — it will work via authenticated browser session.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
git commit -m "test(signal-calendar): Phase 2 visual-verification fixture (5 status states)"
```

---

### Task 5: Browser visual verification

**Files:** none (read-only verification)

**Why:** The acceptance criterion for Phase 2 is "frontend 7-day grid renders chips with correct colors per state". The only meaningful test is opening the page and looking at it.

- [ ] **Step 1: Navigate to the calendar tab**

Use the Playwright MCP plugin:
```
browser_navigate http://192.168.1.200:3000/tools/department-hq
```
Then sign in (`admin` / `Kyt$13ran2025` per `.claude/rules/frontend.md`), click **S.I.G.N.A.L.** main tab, click **Calendar** sub-tab. If the account selector shows `Kytran Katarn` first, click `🏢 Kytran Empowerment Inc.` so the fixture rows (post_type='company') become visible.

- [ ] **Step 2: Capture screenshot**

```
browser_take_screenshot signal-calendar-phase2.png
```

- [ ] **Step 3: Verify chip colors against the spec table**

Open the screenshot and confirm:
- Today's cell has cyan border + glow
- 🇨🇦 ✓ POSTED chip is **green** (#22c55e) on Monday
- ⚜️ ⏳ PENDING chip is **amber** (#f59e0b) on today
- 🇨🇦 ⟳ EXECUTING chip is **blue** (#3b82f6) on today, pulsing
- 🇨🇦 ✗ FAILED chip is **red** (#ef4444) on yesterday
- ⚜️ 🚫 REJECTED chip is **grey** (#9ca3af) on Wednesday
- Empty days show a single dashed `+ Draft now` ghost slot
- Legend row at the bottom shows all 6 status colors with labels
- Header reads "Living Dashboard — Week of YYYY-MM-DD · Account: company"

If any chip is the wrong color, fix the `_SIGNAL_STATUS_VISUALS` constant before continuing.

- [ ] **Step 4: Verify chip click logs to console**

Open browser devtools (Playwright `browser_console_messages` after a click).

```
browser_click signal-chip-element  # whichever chip you clicked
browser_console_messages
```

Expected: a `[SIGNAL chip click] { approvalId: <number>, status: '<status>' }` line. This confirms the Phase 3 hook point is wired.

- [ ] **Step 5: Clean up the fixture**

Once verified, remove the fixture data:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "DELETE FROM autonomy_approval_queue WHERE reason LIKE '[PHASE2_FIXTURE]%';"
```
Expected: `DELETE 5`.

- [ ] **Step 6: Commit screenshot to docs**

```bash
mkdir -p /mnt/archie_brain/docs/superpowers/screenshots
mv signal-calendar-phase2.png /mnt/archie_brain/docs/superpowers/screenshots/2026-05-04-signal-calendar-phase2.png
git add docs/superpowers/screenshots/2026-05-04-signal-calendar-phase2.png
git commit -m "docs(signal-calendar): Phase 2 visual verification screenshot"
```

---

### Task 6: Push branch and open PR

**Files:** none (git only)

- [ ] **Step 1: Create feature branch and push**

If not already on a feature branch (per CLAUDE.md no-direct-to-main rule), this whole plan should run on `feat/signal-calendar-phase2` from the start of Task 1. If you've been committing on `main` accidentally, branch from current state and reset main:

```bash
# If commits already on main locally (post-merge of #532), branch them off:
git checkout -b feat/signal-calendar-phase2
git push -u origin feat/signal-calendar-phase2
```

If you started Task 1 fresh on a branch already, just push:
```bash
git push -u origin feat/signal-calendar-phase2
```

- [ ] **Step 2: Verify GitHub rate limit before opening PR**

Run:
```bash
gh api /rate_limit --jq '.resources.core | {remaining, limit}'
```
Expected: `remaining` > 4000 of 5000.

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "feat(signal-calendar): Phase 2 — frontend chip-grid living dashboard" --body "$(cat <<'EOF'
## Summary

Phase 2 of the SIGNAL Calendar Living Dashboard. Replaces the static theme-schedule grid in DHQ → S.I.G.N.A.L. → Calendar with a 7-day chip-grid that renders the actual lifecycle state of every LinkedIn post (drafted → pending → executing → posted | failed | rejected) by consuming the `GET /api/signal/calendar/live` endpoint shipped in PR #532.

- New `_SIGNAL_STATUS_VISUALS` map: status → bg color + icon + label
- `_renderSignalChip(post)` + `_renderSignalDayCell(day, abbr)` helpers
- `renderSignalCalendar(el)` rewired to fetch `/api/signal/calendar/live?account=<x>`
- Calendar tab TTL dropped 300s → 30s (living dashboard cadence)
- Chip click handler stubbed (`_onSignalChipClick`) — Phase 3 fills the modal
- Empty days show a single dashed "+ Draft now" ghost slot (no action wired — Phase 4)
- Legend row beneath the grid for status color reference

## Test plan

- [x] `node -c department-hq.js` syntax check
- [x] Endpoint still returns 401 unauth after restart (route registered)
- [x] DB fixture seeds 5 status states; calendar shows correct chip colors
- [x] Today's cell highlighted with cyan border + glow
- [x] Chip click logs `{approvalId, status}` to console (Phase 3 hook point)
- [x] Empty days show "+ Draft now" ghost
- [x] Fixture cleaned up after verification

## Spec / Plan

- Design: `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md`
- Phase 2 plan: `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase2.md`
- Phase 1 PR: #532 (merged)

## Out of scope (later phases)

- Phase 3: click-through modal (header + content + timeline + actions)
- Phase 4: action endpoints (retry, draft-now, abandon)
- Phase 5: SSE / real-time push (v1 stays on 30s polling)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait for CI + CodeRabbit review**

```bash
sleep 60 && gh pr view --json statusCheckRollup,mergeStateStatus,number,url
```
Expected: `mergeStateStatus: CLEAN`, CodeRabbit `state: SUCCESS`.

- [ ] **Step 5: Squash-merge and delete branch**

If checks pass:
```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```

---

## Self-Review

**Spec coverage:** Per design spec §3 (Frontend chip component), §7 (Polling integration partial — TTL drop), the visual matrix in the chip table, and the acceptance checklist items 2 ("Frontend 7-day grid renders chips with correct colors per state") and 8 ("30s polling auto-refreshes chip status without page reload"). Acceptance items 3, 4, 5, 6, 7 are explicitly Phase 3+4 scope per the design's Implementation phases table — out of scope here.

**Placeholder scan:** All code blocks contain literal source. No "TBD" / "implement later" / "similar to". `_onSignalChipClick` is named a stub but the body is real (console.log + comment for Phase 3).

**Type consistency:** `_SIGNAL_STATUS_VISUALS` keys match `services/signal_post_status.py` classifier output (`posted`, `pending`, `executing`, `failed`, `rejected`, `deferred`). `post.lang`, `post.approval_id`, `post.status` field names match `_row_to_post` in `services/signal_calendar_live_service.py`. Helper names (`_renderSignalChip`, `_renderSignalDayCell`, `_renderSignalLegend`) used consistently across Tasks 2 and 3.

**Risk / known gaps:**
1. The `node -c` syntax check is the only static validation — no JS linter in this repo. Visual browser test in Task 5 is the real check.
2. Fixture in Task 4 inserts directly into prod-shaped tables. Cleanup is part of the task. If something interrupts Step 5 of Task 5, the cleanup query in Task 5 Step 5 must be run manually before the next session.
3. `executing` chip uses `bmLightPulse` animation defined in the consciousness template. If the calendar tab loads before consciousness assets, the pulse may not animate — degrades gracefully to a static blue chip.
