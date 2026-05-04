# SIGNAL Calendar Living Dashboard — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Phase 2 calendar chips to a click-through LCARS modal that shows full post content, the lifecycle timeline (drafted → approved → executed), error diagnostics on failures, and state-dependent action buttons. Approve/Reject buttons call existing endpoints; Retry/Abandon/Draft-now buttons are stubbed for Phase 4. Telegram deep-link is shown as readable text only (no clickable link) — `TELEGRAM_CHAT_ID=7445959203` is a private DM, not a group, and Telegram has no deep-link format for specific messages in private chats; this defers cleanly to Phase 4+ if needed.

**Architecture:** Backend adds one field (`content`) to the existing `/api/signal/calendar/live` response. Frontend introduces `_openSignalPostModal(post)` and `_closeSignalPostModal()` that render an LCARS `bm-overlay > bm-shell` modal pattern (used elsewhere in `department-hq.js`) with header / content / timeline / actions sections. Chip click handler reads the post from a JS-side cache keyed by `approval_id` (populated when `renderSignalCalendar` runs) — no extra fetch needed. Approve/Reject reuse existing `POST /api/signal/pending/<id>/{approve,deny}` endpoints (already wired in pending-tab JS at lines 1808 / 1894 — same pattern). All HTML insertion goes through the existing `setHtml(el, html)` helper with `esc()` wrapping every user-controllable interpolation — codebase XSS pattern preserved.

**Tech Stack:** Vanilla JS in single-file convention. Python service tweak. Reuses existing `bm-overlay` LCARS modal pattern, `setHtml(el, html)` helper, `apiPost(url, body)` helper, `_signalCalendarPostCache` (new JS dict). Visual verification via Playwright.

**Spec:** `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (see "Component 4: Click-through modal" + "Component 5: Telegram synchronization" + "Component 6: Action endpoints (mostly reuse)")
**Phase 1 plan:** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md`
**Phase 2 plan:** `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase2.md`

---

## Phase 3 scope decisions (locked-in)

| Question | Decision | Note |
|---|---|---|
| Action buttons | Approve/Deny WIRED via existing endpoints; Retry/Abandon/Draft-now STUBBED (alert "Phase 4 — coming soon"); Open on LinkedIn uses `post.linkedin_url` directly; Close closes modal | matches design spec §6 reuse table |
| Full content | Extend `_row_to_post` to include full `content` field (alongside truncated `preview`) | one-line backend change |
| Telegram deep-link | Show as readable text "Telegram msg #<id>" in timeline — NO clickable link | private DM has no deep-link format |
| Phase 2 follow-up | Add `post.approval_id || 0` null-guard in chip onclick | flagged by Task 5 reviewer |

---

## Modal section design (locked-in)

```
+-----------------------------------------------------------------+
| HEADER bar: KE Inc. * 2026-05-04 (MON) * EN * [POSTED]          |
+-----------------------------------------------------------------+
| CONTENT                                                         |
|   <full post text, max-height 280px scrollable>                 |
+-----------------------------------------------------------------+
| ERROR (only if status='failed')                                 |
|   Could not find Start a post button                            |
+-----------------------------------------------------------------+
| TIMELINE                                                        |
|   13:00 v Drafted                                               |
|   13:05 v Approved                                              |
|   13:10 v Posted to LinkedIn                                    |
|   Telegram msg #9001                                            |
+-----------------------------------------------------------------+
| ACTIONS (state-dependent — see table below)                     |
+-----------------------------------------------------------------+
```

| status | actions row |
|---|---|
| posted | `[Open on LinkedIn]` `[Close]` |
| pending | `[Approve]` `[Reject]` `[Close]` |
| executing | `[Close]` (read-only — currently posting) |
| failed | `[Retry (Phase 4)]` `[Mark Won't Fix (Phase 4)]` `[Close]` |
| rejected | `[Re-draft (Phase 4)]` `[Close]` |
| deferred | `[Reconnect (Phase 5)]` `[Close]` |

Phase 4-stubbed buttons render with reduced opacity and trigger `alert('Phase 4 - coming soon. Use Telegram bot for now.')` on click.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `platform_v2/services/signal_calendar_live_service.py` | Modify (`_row_to_post` lines 50-99) | Add `content` field (full text, no truncation) alongside existing `preview` |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify | Replace stub `_onSignalChipClick`; add `_signalCalendarPostCache` dict + cache-population in `renderSignalCalendar`; add `_openSignalPostModal(post)` + `_closeSignalPostModal()` + helpers `_renderModalHeader`, `_renderModalContent`, `_renderModalError`, `_renderModalTimeline`, `_renderModalActions`; add `_signalApprovePost`/`_signalRejectPost` |
| `platform_v2/tests/test_signal_calendar_live_service.py` | Modify | Add `test_row_to_post_includes_full_content` |
| `platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql` | Reuse (re-apply for verification) | Same 5 status states |

The chip-grid file from Phase 2 stays as-is except for the chip onclick line (null-guard) and the new `_signalCalendarPostCache` integration.

---

### Task 1: Backend — add full `content` to calendar response

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/services/signal_calendar_live_service.py:50-99` (the `_row_to_post` function)
- Modify: `/mnt/archie_brain/platform_v2/tests/test_signal_calendar_live_service.py` (add one test)

**Why:** Phase 1 returned only `preview` (200-char truncation). The modal needs the full text. Cheapest tweak: add a `content` field alongside.

- [ ] **Step 1: Read the current `_row_to_post` function**

```bash
sed -n '50,100p' /mnt/archie_brain/platform_v2/services/signal_calendar_live_service.py
```
Confirm the current return dict at lines 87-99 includes `preview` but not `content`.

- [ ] **Step 2: Write the failing test FIRST (TDD)**

Open `/mnt/archie_brain/platform_v2/tests/test_signal_calendar_live_service.py` and add at the end of the relevant test class (read the file first to confirm the class name — likely `TestRowToPost` or similar):

```python
    def test_row_to_post_includes_full_content(self):
        """Phase 3: response must carry full content for modal display."""
        long_text = "X" * 500  # well over the 200-char preview cap
        row = {
            "id": 99,
            "status": "executed",
            "action_data": {"post_type": "company", "language": "en", "content": long_text},
            "execution_result": {"success": True},
            "reason": "[TEST]",
            "created_at": datetime(2026, 5, 4, 13, 0),
            "approved_at": None,
            "executed_at": None,
            "telegram_message_id": None,
            "post_type": "company",
            "post_log_status": None,
            "post_url": None,
        }
        post = _row_to_post(row)
        self.assertEqual(post["content"], long_text)  # full content present
        self.assertTrue(len(post["preview"]) <= 203)  # preview still truncated (200 + "...")
```

If `_row_to_post` and `datetime` aren't imported in the test module, add to the imports at the top:
```python
from datetime import datetime
from services.signal_calendar_live_service import _row_to_post
```

- [ ] **Step 3: Run the test — should FAIL**

```bash
cd /mnt/archie_brain && docker exec archie_platform pytest platform_v2/tests/test_signal_calendar_live_service.py -k test_row_to_post_includes_full_content -v 2>&1 | tail -20
```
Expected: AssertionError on `post["content"]` — KeyError on `'content'`.

- [ ] **Step 4: Make it pass — add `content` field**

Edit `signal_calendar_live_service.py`. Find the return statement in `_row_to_post` (lines 87-99) and add `"content": content,` immediately after the existing `"preview": preview,` line:

Current:
```python
    return {
        "approval_id": row["id"],
        "lang": lang,
        "status": status,
        "post_type": row.get("post_type"),
        "drafted_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
        "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else None,
        "linkedin_url": row.get("post_url"),
        "preview": preview,
        "telegram_message_id": row.get("telegram_message_id"),
        "error": error,
    }
```

New:
```python
    return {
        "approval_id": row["id"],
        "lang": lang,
        "status": status,
        "post_type": row.get("post_type"),
        "drafted_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
        "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else None,
        "linkedin_url": row.get("post_url"),
        "preview": preview,
        "content": content,
        "telegram_message_id": row.get("telegram_message_id"),
        "error": error,
    }
```

- [ ] **Step 5: Run the test — should PASS**

```bash
cd /mnt/archie_brain && docker exec archie_platform pytest platform_v2/tests/test_signal_calendar_live_service.py -k test_row_to_post_includes_full_content -v 2>&1 | tail -10
```
Expected: PASSED.

- [ ] **Step 6: Run the existing service test suite to verify no regression**

```bash
cd /mnt/archie_brain && docker exec archie_platform pytest platform_v2/tests/test_signal_calendar_live_service.py -v 2>&1 | tail -20
```
Expected: all tests PASS (existing 12 + new 1 = 13).

- [ ] **Step 7: Restart platform and verify endpoint returns content**

```bash
docker compose restart archie_platform
sleep 6
docker exec archie_platform python3 -c "
from services.signal_calendar_live_service import get_week_view
import json
r = get_week_view('company')
posts = sum((d['posts'] for d in r['days']), [])
print('total posts:', len(posts))
if posts:
    p = posts[0]
    print('keys:', sorted(p.keys()))
    print('has content key:', 'content' in p)
    print('content len:', len(p.get('content','')))
    print('preview len:', len(p.get('preview','')))
"
```
Expected: `keys` list includes `'content'`. Note: this only shows real posts in the current week, may be empty before fixture re-apply.

- [ ] **Step 8: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/services/signal_calendar_live_service.py platform_v2/tests/test_signal_calendar_live_service.py && git commit -m "feat(signal-calendar): add full content field to calendar/live response (Phase 3)"
```

---

### Task 2: Frontend — modal helpers (LCARS bm-overlay shell)

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js` — insert immediately after `_renderSignalLegend()` function (which is right after `renderSignalCalendar` cluster).

**Why:** Build the modal rendering machinery without yet wiring it. Lets us iterate on visuals separately from click integration. Modal helpers are pure: take post object → return HTML string. The shell creation uses the existing `setHtml(el, html)` helper that the rest of this file relies on (XSS posture preserved by `esc()` wrapping every user-controllable interpolation).

- [ ] **Step 1: Insert modal helpers**

Find the closing brace of `_renderSignalLegend()` in the file (around line 2061 after Phase 2). Immediately after it, insert this block:

```javascript
// ===== Phase 3: SIGNAL post modal =====

// JS-side cache populated by renderSignalCalendar — keyed by approval_id.
var _signalCalendarPostCache = {};

function _signalAccountLabel(account) {
    if (account === 'company')  return 'KE Inc.';
    if (account === 'personal') return 'Kytran Katarn';
    if (account === 'creed')    return 'Creed-AI';
    return esc(account || '');
}

function _signalDayLabel(dateStr) {
    if (!dateStr) return '';
    var DAYS = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
    try {
        var d = new Date(dateStr + 'T12:00:00');  // noon UTC to dodge tz edges
        return DAYS[d.getUTCDay()] + ' ' + dateStr;
    } catch (e) { return dateStr; }
}

function _renderModalHeader(post, account) {
    var v = _SIGNAL_STATUS_VISUALS[post.status] || _SIGNAL_STATUS_VISUALS.failed;
    var langEmoji = _SIGNAL_LANG_EMOJI[post.lang] || '';
    var langLabel = post.lang === 'fr' ? 'FR' : (post.lang === 'en' ? 'EN' : esc((post.lang||'??').toUpperCase()));
    var dayDate = (post.drafted_at || '').substring(0, 10);
    return '<div style="padding:14px 18px;border-bottom:1px solid #1a1a1a;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
        +     '<span style="color:#aaa;font-family:\'Antonio\',sans-serif;font-size:0.7rem;letter-spacing:1px;">'
        +         esc(_signalAccountLabel(account))
        +     '</span>'
        +     '<span style="color:#555;">·</span>'
        +     '<span style="color:#888;font-size:0.65rem;">' + esc(_signalDayLabel(dayDate)) + '</span>'
        +     '<span style="color:#555;">·</span>'
        +     '<span style="font-size:0.7rem;">' + esc(langEmoji) + ' ' + langLabel + '</span>'
        +     '<div style="flex:1;"></div>'
        +     '<span style="background:' + v.bg + ';color:' + v.fg + ';border-radius:4px;'
        +              'padding:4px 10px;font-family:\'IBM Plex Mono\',monospace;'
        +              'font-size:0.55rem;font-weight:700;letter-spacing:1px;">'
        +         esc(v.icon) + ' ' + esc(v.label)
        +     '</span>'
        + '</div>';
}

function _renderModalContent(post) {
    var content = post.content || post.preview || '';
    if (!content) {
        return '<div style="padding:14px 18px;color:#555;font-style:italic;font-size:0.65rem;">'
             + '(no content)</div>';
    }
    return '<div style="padding:14px 18px;">'
        +     '<div style="color:#666;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Content'
        +     '</div>'
        +     '<div style="background:#0d1117;border:1px solid #1a1a1a;border-radius:4px;'
        +              'padding:10px 12px;color:#bbb;font-size:0.7rem;line-height:1.5;'
        +              'max-height:280px;overflow-y:auto;white-space:pre-wrap;">'
        +         esc(content)
        +     '</div>'
        + '</div>';
}

function _renderModalError(post) {
    if (!post.error) return '';
    return '<div style="padding:0 18px 14px;">'
        +     '<div style="color:#ef4444;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Error'
        +     '</div>'
        +     '<div style="background:#1a0404;border:1px solid #ef4444;border-radius:4px;'
        +              'padding:10px 12px;color:#fca5a5;font-size:0.65rem;line-height:1.5;font-family:\'IBM Plex Mono\',monospace;">'
        +         esc(post.error)
        +     '</div>'
        + '</div>';
}

function _renderModalTimeline(post) {
    var rows = '';
    function fmt(iso) {
        if (!iso) return '';
        try { return iso.substring(11, 16) + ' UTC'; }
        catch (e) { return ''; }
    }
    if (post.drafted_at)  rows += '<div style="margin-bottom:6px;">v <span style="color:#666;">' + esc(fmt(post.drafted_at)) + '</span> Drafted</div>';
    if (post.approved_at) rows += '<div style="margin-bottom:6px;">v <span style="color:#666;">' + esc(fmt(post.approved_at)) + '</span> Approved</div>';
    if (post.executed_at) {
        var verb = post.status === 'posted' ? 'Posted to LinkedIn'
                 : post.status === 'failed' ? 'Skill execution failed'
                 : 'Executed';
        var mark = post.status === 'failed' ? 'x' : 'v';
        rows += '<div style="margin-bottom:6px;">' + mark
             + ' <span style="color:#666;">' + esc(fmt(post.executed_at)) + '</span> ' + esc(verb) + '</div>';
    }
    if (post.telegram_message_id) {
        rows += '<div style="margin-bottom:6px;color:#888;">Telegram msg #' + esc(String(post.telegram_message_id)) + '</div>';
    }
    if (!rows) {
        rows = '<div style="color:#555;font-style:italic;">(no timeline events yet)</div>';
    }
    return '<div style="padding:0 18px 14px;">'
        +     '<div style="color:#666;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Timeline'
        +     '</div>'
        +     '<div style="font-size:0.65rem;color:#aaa;font-family:\'IBM Plex Mono\',monospace;">'
        +         rows
        +     '</div>'
        + '</div>';
}

function _phase4Stub(label) {
    var safe = String(label).replace(/'/g, "\\'");
    return ' onclick="alert(\'' + safe + ' - Phase 4. Use Telegram bot for now.\')"';
}

function _renderModalActions(post) {
    var btns = '';
    var btnBase = 'background:#1f2937;color:#e5e7eb;border:1px solid #374151;'
                + 'border-radius:4px;padding:8px 14px;cursor:pointer;'
                + 'font-family:\'Antonio\',sans-serif;font-size:0.7rem;letter-spacing:1px;'
                + 'text-transform:uppercase;';
    var aid = post.approval_id || 0;

    if (post.status === 'posted' && post.linkedin_url) {
        btns += '<a href="' + esc(post.linkedin_url) + '" target="_blank" rel="noopener" '
             +    'style="' + btnBase + 'background:#22c55e;color:#04130a;border-color:#16a34a;text-decoration:none;">'
             +    'Open on LinkedIn'
             + '</a>';
    }
    if (post.status === 'pending') {
        btns += '<button type="button" style="' + btnBase + 'background:#22c55e;color:#04130a;border-color:#16a34a;" '
             +    'onclick="_signalApprovePost(' + aid + ')">'
             +    'Approve'
             + '</button>';
        btns += '<button type="button" style="' + btnBase + 'background:#ef4444;color:#1a0404;border-color:#dc2626;" '
             +    'onclick="_signalRejectPost(' + aid + ')">'
             +    'Reject'
             + '</button>';
    }
    if (post.status === 'failed') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Retry') + '>Retry</button>';
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub("Mark Won't Fix") + ">Mark Won't Fix</button>";
    }
    if (post.status === 'rejected') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Re-draft') + '>Re-draft</button>';
    }
    if (post.status === 'deferred') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Reconnect') + '>Reconnect</button>';
    }
    btns += '<button type="button" style="' + btnBase + '" onclick="_closeSignalPostModal()">Close</button>';

    return '<div style="padding:14px 18px;border-top:1px solid #1a1a1a;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;">'
        +     btns
        + '</div>';
}

function _openSignalPostModal(post) {
    if (!post) return;
    _closeSignalPostModal();  // close any existing instance first

    var account = signalAccount || post.post_type || 'company';

    var overlay = document.createElement('div');
    overlay.className = 'bm-overlay active bm-signal-post-modal';
    overlay.style.cssText = '--bm-accent:#22d3ee;--bm-accent-rgb:34,211,238;';
    overlay.onclick = function(e) { if (e.target === overlay) _closeSignalPostModal(); };

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.cssText = 'max-width:680px;background:#070b10;color:#e5e7eb;border-radius:8px;'
                        + 'border:1px solid #1f2937;overflow:hidden;display:flex;flex-direction:column;';
    shell.onclick = function(e) { e.stopPropagation(); };

    // Use the existing setHtml() helper — same XSS posture as the rest of this file
    // (esc() wraps every user-controllable interpolation in the section helpers above)
    setHtml(shell,
        _renderModalHeader(post, account)
      + _renderModalContent(post)
      + _renderModalError(post)
      + _renderModalTimeline(post)
      + _renderModalActions(post)
    );

    overlay.appendChild(shell);
    document.body.appendChild(overlay);
}

function _closeSignalPostModal() {
    var existing = document.querySelector('.bm-overlay.bm-signal-post-modal');
    if (existing) existing.remove();
}
```

- [ ] **Step 2: Sanity-check syntax**

```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit (helpers exist but not yet called)**

```bash
cd /mnt/archie_brain && git add platform_v2/tools/department_hq/static/js/department-hq.js && git commit -m "feat(signal-calendar): modal helpers + LCARS bm-overlay shell (Phase 3)"
```

---

### Task 3: Frontend — wire chip clicks to modal + cache + null-guard

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js`

**Why:** Glue task. Replaces the Phase 2 stub `_onSignalChipClick` with a real opener. Adds the JS-side post cache populated by `renderSignalCalendar`. Adds approve/reject handlers that hit existing endpoints. Adds the `post.approval_id || 0` null-guard from Phase 2 follow-up review.

- [ ] **Step 1: Replace `_onSignalChipClick` to open the modal**

Find the existing `_onSignalChipClick` (Phase 2 stub):
```javascript
// Phase 3 will replace this stub with the modal opener.
function _onSignalChipClick(approvalId, status) {
    console.log('[SIGNAL chip click]', { approvalId: approvalId, status: status });
    // Phase 3: openSignalPostModal(approvalId);
}
```

Replace with:
```javascript
function _onSignalChipClick(approvalId, status) {
    var post = _signalCalendarPostCache[approvalId];
    if (!post) {
        console.warn('[SIGNAL chip click] post not in cache', approvalId);
        return;
    }
    _openSignalPostModal(post);
}
```

- [ ] **Step 2: Populate `_signalCalendarPostCache` inside `renderSignalCalendar`**

Find `renderSignalCalendar`. Locate the line `var days = data.days || [];`. Immediately after that line, insert cache population:

```javascript
    // Phase 3: populate post cache so chip clicks can look up full post object
    _signalCalendarPostCache = {};
    for (var di = 0; di < days.length; di++) {
        var dposts = days[di].posts || [];
        for (var pi = 0; pi < dposts.length; pi++) {
            if (dposts[pi].approval_id != null) {
                _signalCalendarPostCache[dposts[pi].approval_id] = dposts[pi];
            }
        }
    }
```

- [ ] **Step 3: Add null-guard to chip onclick (Phase 2 follow-up)**

In `_renderSignalChip`, find:
```javascript
        + ' onclick="_onSignalChipClick(' + post.approval_id + ',\'' + post.status + '\')"'
```

Replace with:
```javascript
        + ' onclick="_onSignalChipClick(' + (post.approval_id || 0) + ',\'' + post.status + '\')"'
```

- [ ] **Step 4: Add `_signalApprovePost` and `_signalRejectPost` handlers**

Insert at the end of the modal helpers cluster (right before `_closeSignalPostModal`):

```javascript
async function _signalApprovePost(approvalId) {
    if (!approvalId) return;
    if (!confirm('Approve this post?')) return;
    try {
        await apiPost('/api/signal/pending/' + approvalId + '/approve', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);  // force-refresh chip status
    } catch (err) {
        alert('Approve failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalRejectPost(approvalId) {
    if (!approvalId) return;
    var reason = prompt('Reason for rejection (optional):', '');
    if (reason === null) return;  // user clicked Cancel
    try {
        await apiPost('/api/signal/pending/' + approvalId + '/deny', { reason: reason || '' });
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Reject failed: ' + (err && err.message ? err.message : String(err)));
    }
}
```

(These mirror the existing pattern in this file at lines ~1808/~1894.)

- [ ] **Step 5: Sanity-check syntax**

```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK`.

- [ ] **Step 6: Restart platform to pick up new JS**

```bash
docker compose restart archie_platform
sleep 6
```

- [ ] **Step 7: Confirm endpoint still healthy**

```bash
docker exec archie_platform python3 -c "
from services.signal_calendar_live_service import get_week_view
r = get_week_view('company')
posts = sum((d['posts'] for d in r['days']), [])
print('content key in response:', 'content' in (posts[0] if posts else {}))
print('total posts:', len(posts))
"
```
Expected: `content key in response: True` if any posts exist; otherwise just confirms no errors thrown.

- [ ] **Step 8: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/tools/department_hq/static/js/department-hq.js && git commit -m "feat(signal-calendar): wire chip clicks to modal + approve/reject handlers + null-guard (Phase 3)"
```

---

### Task 4: Visual verification across all 5 chip statuses

**Files:** none (read-only verification + screenshot capture). Cleanup of fixture rows happens at the end.

**Why:** The only acceptance test for a UI-heavy phase like this is opening it in a browser and clicking through every state.

- [ ] **Step 1: Re-apply the fixture (it was cleaned up at the end of Phase 2)**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
```
Expected: 5 INSERTs, then SELECT showing 5 rows.

- [ ] **Step 2: Navigate to Calendar tab via Playwright**

Use Playwright MCP plugin tools (`mcp__plugin_playwright_playwright__browser_*`):
1. `browser_navigate` to `http://192.168.1.200:3000/login` (or dashboard if already authed)
2. Log in: `admin` / `Kyt$13ran2025`
3. Navigate to `http://192.168.1.200:3000/tools/department-hq`
4. Click S.I.G.N.A.L. main tab → Calendar sub-tab
5. Click `KE Inc.` account button (fixture rows are `post_type='company'`)

- [ ] **Step 3: For each chip status, click and verify modal**

For each of the 5 fixture chips (POSTED, PENDING, EXECUTING, FAILED, REJECTED), use `browser_click` on the chip then verify:
- Modal opens with cyan accent
- Header shows account label + day + lang + correct status badge color
- Content section shows the full fixture text (e.g. "[PHASE2_FIXTURE] posted EN sample content")
- Timeline shows correct events for the status (POSTED has all 3 timestamps; PENDING has only Drafted; EXECUTING has Drafted+Approved; FAILED has Drafted+Approved+Failed; REJECTED has only Drafted)
- Telegram msg ID shows as text ("Telegram msg #9001..9005")
- Action row shows correct buttons per status table
- For FAILED chip: error message visible in red error block

After verifying each, click **Close** to dismiss the modal before clicking the next chip.

Take a screenshot of each modal:
```
mcp__plugin_playwright_playwright__browser_take_screenshot   filename: signal-calendar-phase3-modal-{status}.png
```
(5 screenshots: posted/pending/executing/failed/rejected)

- [ ] **Step 4: Test approve button on PENDING chip**

1. Click PENDING chip → modal opens with `[Approve] [Reject] [Close]`
2. Click `Approve` → confirm dialog → click OK
3. Modal should close, calendar should re-render within 1-2s
4. Verify PENDING chip transitions to a new status. The fixture row 9002 has language='fr' so it'll fire `signal_linkedin_post` for the French post — which may fail since this is just a test fixture, but the state transition will happen.
5. Take screenshot of post-approve state

If the approve flow errors (e.g., fixture row doesn't have valid action_data for skill execution), that's expected — the calendar should still update to show the state change.

- [ ] **Step 5: Test reject button on a different fixture row**

Re-apply the fixture (since approve consumed one row), then click PENDING chip → click `Reject` → enter "test reject" → OK. Verify modal closes and the chip becomes REJECTED.

- [ ] **Step 6: Test stub buttons on FAILED chip**

Click FAILED chip → click `Retry`. Expect alert "Retry - Phase 4. Use Telegram bot for now." Click OK. Verify modal stays open (the alert was a stub; no state change).

- [ ] **Step 7: Clean up fixture**

```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM autonomy_approval_queue WHERE reason LIKE '[PHASE2_FIXTURE]%';"
```
Expected: `DELETE N` (N = however many fixture rows remain).

- [ ] **Step 8: Move screenshots into repo and commit**

```bash
mkdir -p /mnt/archie_brain/docs/superpowers/screenshots
mv /tmp/signal-calendar-phase3-modal-*.png /mnt/archie_brain/docs/superpowers/screenshots/
cd /mnt/archie_brain && git add docs/superpowers/screenshots/signal-calendar-phase3-modal-*.png && git commit -m "docs(signal-calendar): Phase 3 modal visual verification screenshots"
```

---

### Task 5: Push branch and open PR

**Files:** none (git only)

- [ ] **Step 1: Verify GitHub rate limit**

```bash
gh api /rate_limit --jq '.resources.core | {remaining, limit}'
```
Expected: `remaining` > 4000.

- [ ] **Step 2: Push the branch**

The plan should run on `feat/signal-calendar-phase3` from Task 1 onwards. If you've been committing on main, branch off and push:
```bash
git push -u origin feat/signal-calendar-phase3
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(signal-calendar): Phase 3 - click-through modal + approve/reject wiring" --body "$(cat <<'EOF'
## Summary

Phase 3 of the SIGNAL Calendar Living Dashboard. Wires the Phase 2 chips to a click-through LCARS modal with full content, lifecycle timeline, error diagnostics, and state-dependent actions.

- Backend: `_row_to_post` adds full `content` field alongside truncated `preview` (one-line tweak + 1 new test)
- Frontend modal helpers: `_openSignalPostModal`, `_closeSignalPostModal`, `_renderModalHeader`, `_renderModalContent`, `_renderModalError`, `_renderModalTimeline`, `_renderModalActions`
- JS-side `_signalCalendarPostCache` keyed by `approval_id` — populated by `renderSignalCalendar`, read by `_onSignalChipClick`
- Approve/Reject buttons wired via existing `POST /api/signal/pending/<id>/{approve,deny}` endpoints (mirror of pending-tab pattern)
- Open on LinkedIn link uses `post.linkedin_url`
- Retry / Abandon / Re-draft / Reconnect buttons stubbed (alert "Phase 4 - coming soon")
- Telegram msg ID shown as text (no clickable link - `TELEGRAM_CHAT_ID=7445959203` is a private DM, no Telegram deep-link format for specific messages in DMs)
- Phase 2 follow-up: `post.approval_id || 0` null-guard in chip onclick

## Test plan

- [x] `pytest test_signal_calendar_live_service.py` - 13 tests pass (12 existing + 1 new)
- [x] `node -c department-hq.js` syntax check
- [x] Endpoint `/api/signal/calendar/live` returns `content` key
- [x] DB fixture seeds 5 status states; modal opens on each chip with correct sections
- [x] Approve button -> confirm -> calls real endpoint -> calendar refreshes
- [x] Reject button -> reason prompt -> calls real endpoint -> calendar refreshes
- [x] Retry/Abandon/Re-draft/Reconnect alert "Phase 4" stub
- [x] Open on LinkedIn link points to `post.linkedin_url`
- [x] Close button dismisses modal
- [x] Click outside modal also dismisses
- [x] Fixture cleaned up after verification

## Spec / Plan

- Design: `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (Components 4, 5, 6)
- Phase 3 plan: `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase3.md`
- Phase 1 PR: #532 (merged)
- Phase 2 PR: #533 (merged)

## Out of scope (later phases)

- Phase 4: action endpoints (POST retry / draft-now / abandon)
- Phase 5: SSE / setInterval polling (v1 stays on TTL-cache + tab-switch refresh)
- Telegram deep-link to specific message in private DM (Telegram has no format for this)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait for CI + CodeRabbit**

```bash
sleep 60 && gh pr view --json statusCheckRollup,mergeStateStatus,mergeable,number,url,reviewDecision
```

- [ ] **Step 5: Squash-merge if clean**

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```

---

## Self-Review

**Spec coverage:** Per design spec §4 (modal sections — header/content/error/timeline/actions), §5 (Telegram synchronization — same backend endpoints, polling propagates), §6 (action endpoints reuse table — approve/deny exist; retry/abandon/draft-now stubbed for Phase 4). The Telegram deep-link section of §5 is partially out of scope due to private-DM constraint — documented in the plan.

**Placeholder scan:** All code blocks contain literal source. Phase 4 stub buttons explicitly call `alert(...)` — not "TODO" placeholders. The `_phase4Stub(label)` helper produces a real onclick attribute with a real alert message.

**Type consistency:** `_signalCalendarPostCache` is a plain JS object keyed by integer `approval_id` (number → object). `_signalApprovePost`/`_signalRejectPost` take an integer `approvalId`. `_openSignalPostModal` takes the full post object (cached or live). `_renderModalHeader/Content/Error/Timeline/Actions` all take the post object and return HTML strings. `_closeSignalPostModal` takes nothing and removes the overlay element.

**Risk / known gaps:**
1. Approving a fixture row will likely fail downstream skill execution because the fixture content isn't a real LinkedIn-postable draft. The state transition (pending → executing) still happens, which is what the test verifies. Real approve flow on real posts will trigger real LinkedIn skill calls — confirmed via existing pending-tab UX which uses the same endpoint.
2. The modal uses `document.body.appendChild(overlay)` rather than rendering into a designated modal root. This is consistent with the existing `bm-provider-modal` pattern at line ~3743 in this file.
3. Click-outside-to-dismiss is wired via `overlay.onclick = ... if (e.target === overlay) close()`. ESC key to dismiss is NOT wired in v1 — minor accessibility gap; trivial to add in Phase 4 if needed.
4. The `_signalDayLabel` uses `new Date(dateStr + 'T12:00:00')` to dodge timezone edges — acceptable for week-view display.
5. `loadSignalTab('calendar', true)` after approve/reject force-refreshes — but the chip state may take 1-2s to actually transition (skill execution time). The user may briefly see the old state.
6. HTML insertion uses the existing `setHtml(el, html)` helper. XSS posture preserved by `esc()` wrapping every user-controllable interpolation in the section helpers (post.error, post.content, post.linkedin_url, post.telegram_message_id, post.lang). Status/icon/label values come from the local `_SIGNAL_STATUS_VISUALS` constant — not user-controllable. Color hex literals in inline styles are constant.
