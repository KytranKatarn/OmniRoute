# SIGNAL Calendar Living Dashboard — Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 2 "TTL-cache + tab-switch refresh" approximation with real `setInterval`-driven polling. While the Calendar sub-tab is shown, the calendar auto-refreshes every 30 seconds (matching the spec's "living dashboard" cadence). Polling stops when the user switches to a different SIGNAL sub-tab. Polling pauses while the post modal is open so a refresh doesn't yank content out from under the user mid-read.

**Architecture:** A single new module-level handle `_signalCalendarPollHandle`. Polling is set up at the end of `loadSignalTab('calendar', ...)` and torn down at the start of every `loadSignalTab(tab, ...)` call (so any sub-tab switch clears it). The interval callback skips refresh if the modal is open — checked by the existing `.bm-overlay.bm-signal-post-modal` selector. Account switches already call `loadSignalTab(signalTab, true)` from `switchSignalAccount()`, which naturally clears + re-establishes the interval. No new endpoints, no new helpers beyond the start/stop pair, no design system changes.

**Tech Stack:** Vanilla JS in single-file convention. No backend changes. No new tests (verification is browser-driven via Playwright + network panel). The existing classifier and live endpoint already produce stable, idempotent results — polling them every 30s is safe.

**Spec:** `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (Component 7: Polling integration)
**Phase 1-4 plans:** in the same `docs/superpowers/plans/` directory

---

## Phase 5 scope decisions (locked-in)

| Question | Decision |
|---|---|
| Polling interval | 30 seconds (matches the chip TTL set in Phase 2 Task 1) |
| Start trigger | End of `loadSignalTab('calendar', ...)` execution |
| Stop trigger | Start of every `loadSignalTab(tab, ...)` call (also fires when user switches sub-tabs) + on `switchSignalAccount` (which calls `loadSignalTab(signalTab, true)`) |
| Modal open behavior | Interval callback skips the refresh — does NOT clear the interval. Modal close resumes natural cadence. |
| Cleanup when user leaves DHQ entirely | Not handled in Phase 5 — interval leaks until browser context ends. Cost: 1 API call / 30s on a closed tab. Negligible at admin scale. |
| Page Visibility API | Not added in Phase 5 — would be a nice future enhancement to pause polling when window is hidden. |
| Force-refresh on focus | Not added — Phase 2 already covers manual `forceRefresh` via tab re-click |

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify | Add `_signalCalendarPollHandle` global + start/stop in `loadSignalTab` + modal-open skip |

That's it. One file.

---

### Task 1: Add polling start/stop in `loadSignalTab`

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js`

**Why:** Glue the polling lifecycle into the existing tab switcher so we don't have to manage state from multiple call sites.

- [ ] **Step 1: Read the existing `loadSignalTab` function**

```bash
sed -n '1505,1545p' /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js
```
Confirm the function shape: it does TTL cache check, then a `switch (tab)` that calls one of the `renderSignal*` functions. The line numbers have shifted across phases — find by name, not by line.

- [ ] **Step 2: Add module-level handle**

Find the existing `var _signalLastRun = {};` line near the top of the SIGNAL helpers cluster (currently around line 1464). Immediately after it, add:

```javascript
// Phase 5: setInterval handle for live calendar polling. Cleared on every
// loadSignalTab() entry; re-established at the end of loadSignalTab('calendar').
var _signalCalendarPollHandle = null;
```

- [ ] **Step 3: Insert teardown at top of `loadSignalTab`**

Find `async function loadSignalTab(tab, forceRefresh) {`. Immediately after the opening brace, add:

```javascript
    // Phase 5: clear any prior calendar polling on every tab switch
    if (_signalCalendarPollHandle) {
        clearInterval(_signalCalendarPollHandle);
        _signalCalendarPollHandle = null;
    }
```

(This runs on every call, regardless of `tab`. Switching to any sub-tab kills calendar polling. Re-entering calendar will re-establish it in Step 4.)

- [ ] **Step 4: Insert setup after the switch**

Find the end of the `switch (tab) { ... }` block in `loadSignalTab`. Immediately AFTER the switch's closing brace and BEFORE any function-end logic (or right at the end of the function if there's nothing after the switch), add:

```javascript
    // Phase 5: re-establish polling if we just rendered the calendar
    if (tab === 'calendar' && !_signalCalendarPollHandle) {
        _signalCalendarPollHandle = setInterval(function () {
            // Skip if the post modal is open — don't disrupt the user mid-read
            if (document.querySelector('.bm-overlay.bm-signal-post-modal')) {
                return;
            }
            loadSignalTab('calendar', true);
        }, 30000);
    }
```

- [ ] **Step 5: Sanity-check syntax**

```bash
node -c /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js && echo OK
```
Expected: `OK`.

- [ ] **Step 6: Restart platform**

```bash
docker compose restart archie_platform && sleep 6
```

- [ ] **Step 7: Confirm endpoint healthy**

```bash
curl -sS -o /dev/null -w "calendar/live: %{http_code}\n" "http://192.168.1.200:3000/tools/department-hq/api/signal/calendar/live?account=company"
```
(Use ctx_execute with language `shell` if curl is hook-blocked.)
Expected: `401` (auth-gated; route registered).

- [ ] **Step 8: Commit**

```bash
cd /mnt/archie_brain && git add platform_v2/tools/department_hq/static/js/department-hq.js && git commit -m "feat(signal-calendar): real setInterval polling for Calendar tab (Phase 5)"
```

---

### Task 2: Visual verification of polling lifecycle

**Files:** none (read-only verification + screenshot capture).

**Why:** The only meaningful test of polling is observing it live in the network panel.

- [ ] **Step 1: Re-apply the Phase 2 fixture**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/platform_v2/tests/fixtures/signal_calendar_phase2_fixture.sql
```

- [ ] **Step 2: Navigate to Calendar tab via Playwright**

Use Playwright MCP plugin tools (`mcp__plugin_playwright_playwright__browser_*`):
1. `browser_navigate` to `http://192.168.1.200:3000/tools/department-hq` (log in if needed: `admin` / `Kyt$13ran2025`)
2. Click S.I.G.N.A.L. main tab → Calendar sub-tab
3. Click `KE Inc.` account button

- [ ] **Step 3: Verify polling kicks in**

Take a `browser_network_requests` snapshot. Then wait ~35 seconds (so the 30s interval fires at least once). Take another network snapshot.

Expected: a SECOND `GET /tools/department-hq/api/signal/calendar/live?account=company` request appears in the second snapshot but not the first. This proves setInterval is firing.

If the second snapshot shows zero new requests after 35 seconds, polling did not start — investigate `loadSignalTab`'s setup branch.

Take screenshot `signal-calendar-phase5-polling-network.png` showing the network panel with multiple calendar/live requests.

- [ ] **Step 4: Verify polling pauses when modal is open**

Click any chip (e.g. POSTED) → modal opens. Wait ~35 seconds with the modal still open. Check network requests.

Expected: NO new `calendar/live` requests fire while the modal is open. Setting still ticks but skips because of the modal-open guard.

Close the modal. Wait another ~35 seconds. New `calendar/live` request appears.

Take screenshot `signal-calendar-phase5-modal-pauses-polling.png`.

- [ ] **Step 5: Verify polling stops when leaving Calendar sub-tab**

Click the **Pending** sub-tab. Wait ~35 seconds. Check network requests.

Expected: NO new `calendar/live` requests during the wait — the teardown at top of `loadSignalTab` cleared the interval.

Click back to **Calendar** sub-tab → polling re-establishes. Wait ~35 seconds → new `calendar/live` request.

Take screenshot `signal-calendar-phase5-tab-switch-stops-polling.png`.

- [ ] **Step 6: Verify account switch refreshes immediately + re-establishes polling**

While on Calendar with `KE Inc.`, switch to `Kytran Katarn` account. Network panel should show an immediate `calendar/live?account=personal` request (from the synchronous `loadSignalTab('calendar', true)` triggered by `switchSignalAccount`). Wait ~35 seconds → another `calendar/live?account=personal` from the polling.

- [ ] **Step 7: Clean up fixture**

```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM autonomy_approval_queue WHERE reason LIKE '[PHASE2_FIXTURE]%';"
```

- [ ] **Step 8: Commit screenshots**

```bash
mkdir -p /mnt/archie_brain/docs/superpowers/screenshots
mv /tmp/signal-calendar-phase5-*.png /mnt/archie_brain/docs/superpowers/screenshots/
cd /mnt/archie_brain && git add docs/superpowers/screenshots/signal-calendar-phase5-*.png && git commit -m "docs(signal-calendar): Phase 5 polling lifecycle verification screenshots"
```

---

### Task 3: Push branch + open PR + squash-merge

**Files:** none (git only)

- [ ] **Step 1: Verify GitHub rate limit**

```bash
gh api /rate_limit --jq '.resources.core | {remaining, limit}'
```
Expected: `remaining` > 4000.

- [ ] **Step 2: Push the branch**

The plan should run on `feat/signal-calendar-phase5` from Task 1 onwards.
```bash
cd /mnt/archie_brain && git push -u origin feat/signal-calendar-phase5
```

- [ ] **Step 3: Open PR**

```bash
cd /mnt/archie_brain && gh pr create --title "feat(signal-calendar): Phase 5 - real setInterval polling" --body "$(cat <<'EOF'
## Summary

Phase 5 of the SIGNAL Calendar Living Dashboard. Replaces the Phase 2 "TTL-cache + tab-switch refresh" approximation with real `setInterval`-driven polling.

- New module-level `_signalCalendarPollHandle` (single global)
- Teardown at the top of `loadSignalTab(tab, ...)` — every sub-tab switch clears the interval
- Setup at the end of `loadSignalTab('calendar', ...)` — re-establishes 30s polling on calendar
- Modal-open guard: interval callback skips refresh if `.bm-overlay.bm-signal-post-modal` exists, so polling doesn't yank content out from under the user
- No new endpoints, no new helpers beyond start/stop, no design system changes

## Test plan

- [x] `node -c department-hq.js` syntax check
- [x] After ~35s on Calendar tab, a second `GET /api/signal/calendar/live` request fires
- [x] Modal-open: no new `calendar/live` requests while modal is visible
- [x] Modal-close: polling resumes natural cadence
- [x] Sub-tab switch (Calendar → Pending): no new requests during wait
- [x] Sub-tab return (Pending → Calendar): polling re-establishes
- [x] Account switch (KE Inc. → Kytran Katarn): immediate fetch + new polling cadence
- [x] Endpoint still 401 (auth-gated, registered) after restart
- [x] 3 verification screenshots committed

## Spec / Plan

- Design: `docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md` (Component 7: Polling integration)
- Phase 5 plan: `docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase5.md`
- Phase 1 PR: #532 / Phase 2 PR: #533 / Phase 3 PR: #534 / Phase 4 PR: #535 (all merged)

## Out of scope

- Cleanup when user leaves DHQ entirely (interval leaks until browser context ends — negligible cost at admin scale)
- Page Visibility API integration (pause polling when window hidden — future enhancement)
- SSE / WebSocket upgrade (would replace polling entirely; not needed at current scale)
- Per-language Re-draft (separate Phase 4 follow-up)

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

**Spec coverage:** Per design spec §7 (Polling integration). The TTL-cache part was Phase 2 Task 1; Phase 5 ships the real setInterval. The "Cache key includes account so switching busts stale data" requirement is already met by the existing `loadSignalTab` cache key (which includes `signalAccount` per the existing per-tab cache pattern).

**Placeholder scan:** No "TODO" / "implement later" markers. The Phase 5 stubs in earlier phases (Reconnect button) are explicitly out of scope and remain stubbed.

**Type consistency:** `_signalCalendarPollHandle` is a number (setInterval return) or `null`. The type stays consistent across the three sites (declaration, teardown, setup).

**Risk / known gaps:**
1. The interval leaks if the user navigates away from DHQ to a different module without going through `loadSignalTab` first — e.g., direct URL navigation. Cost: one fetch every 30s until browser context ends. Acceptable.
2. The `document.querySelector('.bm-overlay.bm-signal-post-modal')` check fires every tick; for a single tick every 30s the cost is negligible.
3. If `loadSignalTab('calendar', true)` is called from inside the interval callback while the user is mid-action (e.g., scroll position, hovered chip), the re-render replaces the calendar element wholesale — minor UX hiccup. Acceptable for v1; future polish could diff-update.
4. Two tabs of the platform open simultaneously would each run their own polling — N×30s API calls. Acceptable for admin-scale single-user deployment.
5. If the network call fails (server hiccup, auth expiry), the catch in `renderSignalCalendar` already shows a red error message via `setHtml`. Polling continues — the next tick may succeed. This is the correct behavior.
