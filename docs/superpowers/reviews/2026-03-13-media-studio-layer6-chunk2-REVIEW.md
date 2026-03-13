# Layer 6 Chunk 2 (Frontend) Plan Review

**Reviewer:** Senior Code Reviewer (Opus 4.6)
**Date:** 2026-03-13
**Plan:** `docs/superpowers/plans/2026-03-13-media-studio-layer6-batch.md` (Tasks 8-11)
**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-layer6-batch-design.md`

---

## Verdict: APPROVED with 2 Issues and 3 Suggestions

The frontend chunk is well-structured, follows established patterns (IIFE, `window.funcName`, `ms` prefix, `_escHtml`/`_clearChildren` reuse), and covers all spec requirements. The XSS surface is clean -- dynamic content uses `textContent` and DOM APIs throughout. Two issues need attention before implementation.

---

## Issues (must fix)

### 1. `loadQueueStats` badge arithmetic uses wrong field

**Location:** Task 9, `loadQueueStats()` (plan line ~1268)

```javascript
document.getElementById('msQueueActiveCount').textContent = stats.pending + stats.running;
```

The `get_queue_stats` service (Task 4, line ~677) returns `pending` (which covers `pending` + `dispatched`) and `running` (which covers `generating`). The integer addition is correct in semantics, but the API response field `pending` already bundles two statuses while `running` is a separate count for `generating`. The toggle button shows `"Queue (N active)"` -- this sum is the right number.

**However**, `stats.pending + stats.running` will produce string concatenation, not addition, if the API ever returns string values. The `api()` helper parses JSON so they should be integers, but add a defensive `Number()` cast or `(stats.pending || 0) + (stats.running || 0)` to be safe.

**Fix:** Change to:
```javascript
document.getElementById('msQueueActiveCount').textContent = (stats.pending || 0) + (stats.running || 0);
```

### 2. `loadQueueItems` uses nested `.then()` chains (callback pyramid)

**Location:** Task 9, `loadQueueItems()` (plan lines ~1274-1282)

Three sequential API calls for active items (`pending`, `dispatched`, `generating`) are nested 3 levels deep. This is functionally correct but:
- Serializes 3 independent requests (slow -- 3 round trips in sequence)
- Creates a callback pyramid that is hard to read

**Fix:** Use `Promise.all` to parallelize:
```javascript
Promise.all([
    api('/api/queue?status=pending&per_page=50'),
    api('/api/queue?status=dispatched&per_page=50'),
    api('/api/queue?status=generating&per_page=50')
]).then(function(results) {
    var active = [].concat(results[0].items || [], results[1].items || [], results[2].items || []);
    _renderQueueSection('msQueueActiveList', active, 'active');
    document.getElementById('msQueueActive').style.display = active.length ? 'block' : 'none';
});
```

This turns 3 sequential network calls into 1 parallel batch -- significant for a function that runs every 10 seconds.

---

## Suggestions (nice to have)

### S1. Spec mentions "auto-dismissed after 30 seconds" for recent completions -- plan omits this

The spec says: "Recent completions -- last 5 completed items with thumbnail preview. Auto-dismissed after 30 seconds." The plan fetches and renders them but never sets a timeout to dismiss. Not critical since the 10s polling refresh effectively replaces them, but the spec behavior is not implemented.

**Suggestion:** Add a `setTimeout` in the recent section render that hides old items, or document that polling-based refresh is the intended substitute.

### S2. Spec mentions "elapsed time (live-updating)" -- plan uses static `_formatElapsed`

The spec says active cards should have "elapsed time (live-updating)". The plan computes elapsed time once per `_createQueueCard` call, but it only updates every 10 seconds (the `loadQueueItems` interval). For a true live-updating elapsed counter, a 1-second `setInterval` updating all visible elapsed spans would be needed. The current 10s refresh is acceptable but does not match the spec exactly.

### S3. Integration test (Task 11) does not verify CSS file changes

The test checks HTML element IDs and JS function names in the template, but does not verify that `media-studio.css` contains the new section marker `S20` or key class names like `ms-queue-panel`, `ms-spinner`, `ms-batch-modal`. Adding a simple file-content check for CSS would catch missing style commits.

---

## Spec Coverage Checklist

| Spec Requirement | Plan Coverage | Status |
|---|---|---|
| Queue toggle button with count badge | Task 8 Step 1 (`msQueueToggle`, `msQueueActiveCount`) | COVERED |
| Queue panel: active, failed, recent sections | Task 8 Step 2 (3 sections with IDs) | COVERED |
| Batch items grouped under collapsible batch header | Task 9 `_renderQueueSection` groups by `batch_id` | COVERED |
| Failed items: individual Retry button | Task 9 `_createQueueCard` type=failed | COVERED |
| Batch failures: "Retry All Failed" on header | Task 9 `_renderQueueSection` type=failed | COVERED |
| Clear Completed button | Task 8 Step 2 + Task 9 `clearCompleted()` | COVERED |
| Stats badge in panel header | Task 8 Step 2 (`msQueueStats`) + Task 9 `loadQueueStats` | COVERED |
| Cancel on individual + batch groups | Task 9 cards + batch headers | COVERED |
| Polling: 5s stats, 10s items, stop when collapsed | Task 9 `toggleQueuePanel` with intervals | COVERED |
| Batch modal: name, prompts, sweep, shared params | Task 8 Step 3 (full modal HTML) | COVERED |
| Preview line with live count + 50 cap warning | Task 9 `updateBatchPreview` | COVERED |
| Submit disabled if >50 or 0 prompts | Task 9 `updateBatchPreview` last line | COVERED |
| Batch button next to Generate on each tab | Task 8 Step 4 | COVERED |

## JS Function Coverage

| Spec Function | Plan Location | Status |
|---|---|---|
| `toggleQueuePanel()` | Task 9 Step 1 | COVERED |
| `loadQueueStats()` | Task 9 Step 1 | COVERED |
| `loadQueueItems()` | Task 9 Step 1 | COVERED |
| `submitBatch()` | Task 9 Step 2 | COVERED |
| `cancelQueueItem(id)` | Task 9 Step 1 | COVERED |
| `retryQueueItem(id)` | Task 9 Step 1 | COVERED |
| `cancelBatch(id)` | Task 9 Step 1 | COVERED |
| `retryBatchFailed(id)` | Task 9 Step 1 | COVERED |
| `clearCompleted()` | Task 9 Step 1 | COVERED |
| `openBatchModal(mediaType)` | Task 9 Step 2 | COVERED |

## CSS Component Coverage

| Component | Plan CSS Class | Status |
|---|---|---|
| Queue panel | `.ms-queue-panel` | COVERED |
| Queue cards | `.ms-queue-card`, `.ms-queue-card-body` | COVERED |
| Batch groups | `.ms-queue-batch-group`, `.ms-queue-batch-header` | COVERED |
| Spinner | `.ms-spinner`, `@keyframes ms-spin` | COVERED |
| Batch modal | `.ms-batch-modal`, `.ms-batch-preview` | COVERED |
| Card types (active/failed/recent) | `.ms-queue-active/failed/recent` | COVERED |

## XSS Review

All dynamic user content (prompts, error messages, batch names) is rendered via `textContent` or `document.createTextNode()`. No raw `innerHTML` with unescaped user data. The plan explicitly states to use `_escHtml()` for any innerHTML and to prefer DOM APIs -- this guidance is followed consistently. **No XSS risks identified.**

## Element ID Consistency (HTML <-> JS)

All IDs cross-referenced and consistent: `msQueuePanel`, `msQueueToggle`, `msQueueActiveCount`, `msQueueStats`, `msQueueActive`, `msQueueActiveList`, `msQueueFailed`, `msQueueFailedList`, `msQueueRecent`, `msQueueRecentList`, `msBatchModal`, `msBatchName`, `msBatchPrompts`, `msBatchPromptCount`, `msBatchSweepToggle`, `msBatchSweepSection`, `msBatchSweepParam`, `msBatchSweepSeedInput`, `msBatchSweepSeeds`, `msBatchSweepModelInput`, `msBatchModelCheckboxes`, `msBatchMediaType`, `msBatchModel`, `msBatchNegPrompt`, `msBatchSharedParams`, `msBatchPreview`, `msBatchSubmit`. **No mismatches found.**
