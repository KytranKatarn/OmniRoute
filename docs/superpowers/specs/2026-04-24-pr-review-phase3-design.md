# PR Review Pipeline — Phase 3: Repair Bay UI

**Date**: 2026-04-24
**Project**: #247 — PR Review Pipeline — Repair Bay Integration
**Task**: #1801 — Phase 3: Repair Bay UI — PR Review tab with diff viewer
**Status**: Approved by user 2026-04-24

---

## Goal

Add a dedicated "PR Review" tab to the Repair Bay module. Kytran can see all tracked PRs, read F.O.R.G.E.'s AI review verdict + summary, and take action (merge, re-review, skip, open diff on GitHub) — all without leaving the platform.

---

## Context: What Phases 1 & 2 Built

- **Table**: `pr_reviews` — `pr_number`, `repo`, `title`, `author`, `state`, `base_branch`, `head_branch`, `diff_url`, `additions`, `deletions`, `changed_files`, `review_status` (pending/in_progress/reviewed/skipped), `ai_summary`, `ai_review_at`
- **Existing routes**: `GET /api/forge/pr-reviews` (list), `GET /api/forge/pr-reviews/<n>` (get), `POST /api/forge/pr-reviews/<n>/analyze` (trigger AI review), `POST /api/forge/pr-reviews/poll` (GitHub poll), `POST /api/forge/pr-reviews/<n>/skip` (skip)
- **Agent loop**: `forge_pr_diff_analysis` job runs every 10 min, auto-reviews pending PRs
- **Tab structure**: 7 existing tabs in `repair_bay.html` using `header_tabs` list. CSS prefix: `dp-`

---

## Architecture

```
User opens PR Review tab
    → loadPRReviews() → GET /api/forge/pr-reviews/list
    → Left pane: PR list (reviewed first, pending last)
    → Click row → prSelectReview(pr) → right pane renders

User clicks "Merge PR"
    → prMerge(prNumber) → POST /api/forge/pr-reviews/<n>/merge
    → GitHub API: PUT /repos/{owner}/{repo}/pulls/{n}/merge
    → Status updated, row removed from active list

User clicks "Re-review"
    → prAnalyze(prNumber) → POST /api/forge/pr-reviews/<n>/analyze (Phase 2 route)
    → Refreshes detail pane when done

User clicks "View Diff on GitHub ↗"
    → Opens https://github.com/{repo}/pull/{pr_number}/files in new tab
```

---

## Components

### 1. New tab entry in repair_bay.html

Add `("pr-review", "PR Review", "git-pull-request")` to `header_tabs` list. Position: after the existing `("reviews", "Reviews", ...)` tab.

### 2. Tab content HTML (repair_bay.html)

New `<div id="tab-pr-review" class="tab-content">` following the LCARS frame pattern:

```
┌─────────────────────────────────────────────────────────────────┐
│ [LCARS sidebar — 56px cyan]  PR REVIEWS          [Refresh]      │
├──────────────────────────┬──────────────────────────────────────┤
│ PR LIST (left 240px)     │ DETAIL PANE (flex:1)                │
│                          │                                      │
│ ● APPROVE  #292          │  #292 — Unified Voice completion     │
│   Unified Voice...       │  Author: dev · main ← feature/...   │
│   F.O.R.G.E. · 2h ago   │  +354 -127 · 8 files                │
│                          │                                      │
│ ⚠ REQUEST  #291          │  ✅ VERDICT: APPROVE                 │
│   KBS Store...           │                                      │
│                          │  SUMMARY                             │
│ ⏳ pending  #290         │  This PR completes the Unified...    │
│   [Analyze Now]          │                                      │
│                          │  ISSUES                              │
│                          │  • [INFO] Dead param report_id       │
│                          │                                      │
│                          │  [Merge PR] [Re-review] [Skip]      │
│                          │  [View Diff on GitHub ↗]            │
└──────────────────────────┴──────────────────────────────────────┘
```

**Left pane** (`dp-pr-list`, 240px):
- Sorted: reviewed (APPROVE → REQUEST CHANGES → NEEDS REVIEW) first, pending/skipped last
- Each row: verdict badge + PR number + truncated title + timestamp
- Pending rows show "Analyze Now" button in place of verdict
- Active row highlighted with `dp-pr-row--active` class

**Right pane** (`dp-pr-detail`):
- Empty state when nothing selected: "Select a PR to view the review"
- Populated state:
  - Title, author, base←head, additions/deletions/files
  - Verdict badge (colour-coded: green=APPROVE, amber=REQUEST CHANGES, blue=NEEDS REVIEW, grey=pending)
  - AI summary paragraph (from `ai_summary` field, parsed at `SUMMARY` / `ISSUES` / `VERDICT` markers)
  - Issues bullet list
  - "View Diff on GitHub ↗" anchor → `https://github.com/{repo}/pull/{pr_number}/files`, `target="_blank"`, `rel="noopener noreferrer"`
  - Action buttons: Merge PR · Re-review · Skip

### 3. New backend route (github_routes.py)

**No new list route needed** — the existing `GET /api/forge/pr-reviews?state=open&limit=50` already returns the right data. The JS uses this directly.

**`POST /api/forge/pr-reviews/<int:pr_number>/merge`**
- Calls GitHub API: `PUT https://api.github.com/repos/{repo}/pulls/{pr_number}/merge`
- Headers: `Authorization: token {GITHUB_TOKEN}`, `Accept: application/vnd.github.v3+json`
- Body: `{"commit_title": "Merge PR #{pr_number}: {title}", "merge_method": "squash"}`
- On success: update `pr_reviews.state = 'merged'` via DB
- Returns: `{success, merged, message}` or `{success: False, error}` on failure
- `@login_required`, `@admin_required`

### 4. JS additions (repair-bay-main.js or inline script)

```javascript
// State
window._prSelectedId = null;
window._prReviewsTimer = null;

// Load and render PR list
function loadPRReviews() { ... }          // GET /api/forge/pr-reviews/list

// Select a PR and render detail
function prSelectReview(pr, allReviews) { ... }
function _prRenderDetail(pr) { ... }      // builds detail pane via DOM methods

// Actions
function prMerge(prNumber, repo) { ... }   // POST merge route
function prAnalyze(prNumber) { ... }       // POST analyze route (Phase 2)
function prSkip(prNumber) { ... }          // POST existing skip route

// Poll
function _startPRReviewPoll() { loadPRReviews(); setInterval(loadPRReviews, 30000); }
function _stopPRReviewPoll() { clearInterval(window._prReviewsTimer); }
```

All dynamic content uses `textContent` / `createElement` — no innerHTML with API data.

### 5. Tab switching wire-up

In the existing `switchTab()` function in `repair_bay.html`:
- When `tabId === 'pr-review'`: call `_startPRReviewPoll()`
- When leaving: call `_stopPRReviewPoll()`

---

## CSS additions (repair_bay.html `<style>` block or existing CSS file)

```css
/* PR Review tab — split pane */
.dp-pr-split { display: flex; height: 480px; border: 1px solid var(--archie-border, #1e293b); border-radius: 6px; overflow: hidden; }
.dp-pr-list { width: 240px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid var(--archie-border, #1e293b); background: var(--archie-surface, #0f172a); }
.dp-pr-row { padding: 10px 14px; border-bottom: 1px solid #1e293b; cursor: pointer; transition: background .1s; }
.dp-pr-row:hover { background: #1e293b33; }
.dp-pr-row--active { background: #1e3a5f; border-left: 3px solid #00d4ff; }
.dp-pr-detail { flex: 1; overflow-y: auto; padding: 20px; background: var(--archie-bg, #0a0e1a); }
.dp-pr-detail--empty { display: flex; align-items: center; justify-content: center; color: var(--archie-muted, #64748b); font-size: 13px; }
.dp-pr-verdict { font-size: 13px; font-weight: 700; margin-bottom: 12px; }
.dp-pr-verdict--approve { color: #22c55e; }
.dp-pr-verdict--request { color: #f59e0b; }
.dp-pr-verdict--needs { color: #7eb8f7; }
.dp-pr-verdict--pending { color: #64748b; }
.dp-pr-summary { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 14px; white-space: pre-wrap; }
.dp-pr-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.dp-pr-github-link { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #00d4ff; text-decoration: none; margin-top: 8px; }
```

---

## `ai_summary` Parsing

The `ai_summary` field contains F.O.R.G.E.'s raw output:
```
SUMMARY
<paragraph>

ISSUES
- [CRITICAL/WARNING/INFO] <issue> — <why>

VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW
```

JavaScript parser extracts:
- `verdict`: line starting with `VERDICT:` → extract `APPROVE`, `REQUEST CHANGES`, or `NEEDS REVIEW`
- `summary`: text between `SUMMARY\n` and `\nISSUES`
- `issues`: lines starting with `-` after `ISSUES`

If parsing fails (old format, empty), show raw `ai_summary` text.

---

## Testing

| Scenario | Expected |
|----------|---------|
| Tab loads with reviewed PRs | Verdict badges coloured, first PR auto-selected, detail pane populated |
| Tab loads with only pending PRs | "Analyze Now" buttons on each row, detail pane empty |
| Click "Merge PR" — success | Row disappears, success toast shown |
| Click "Merge PR" — GitHub API failure | Error message shown in detail pane, PR not removed |
| Click "Re-review" | Detail pane shows loading state, refreshes with new AI summary |
| Click "View Diff on GitHub ↗" | Opens PR files-changed URL in new tab |
| 30s poll | List refreshes; if background analysis completed, pending row gets verdict |
