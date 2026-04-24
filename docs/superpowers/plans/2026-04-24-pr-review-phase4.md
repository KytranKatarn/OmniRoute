# PR Review Phase 4 — Telegram Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a Telegram notification (verdict + summary snippet + URL buttons) when F.O.R.G.E. completes a PR review.

**Architecture:** `pr_diff_analyzer` submits to inbox with `category="pr_reviewed"` after each review. A DB triage policy auto-escalates this category. The archie_comms escalation handler adds URL buttons (Repair Bay + GitHub) before sending to Telegram.

**Tech Stack:** Python, PostgreSQL (triage_policies table), archie_comms Telegram service, `submit_via_inbox`.

---

## File Map

| File | Action | Change |
|------|--------|--------|
| `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py` | Modify | Add `_notify_pr_reviewed()` + call after `mark_review_done()` |
| `archie-comms/services/telegram_service.py` | Modify | Add `pr_reviewed` keyboard block in escalation handler |
| DB (`archie` database) | Migrate | Insert triage policy row for `pr_reviewed` category |

---

## Task 1: Add _notify_pr_reviewed to pr_diff_analyzer

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`

- [ ] **Step 1: Check if `import re` already exists**

  ```bash
  grep -n "^import re" /mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_diff_analyzer.py
  ```

  If not present, add `import re` after `import os` at the top of the file.

- [ ] **Step 2: Add `_notify_pr_reviewed` function**

  Add this function at the end of `pr_diff_analyzer.py`, before the closing (after `_run_forge_review`):

  ```python
  def _notify_pr_reviewed(pr_number: int, repo: str, title: str, ai_summary: str) -> None:
      """Submit a PR review completion notification to the director_reports inbox.

      Submitting to inbox (not Telegram directly) so it flows through the
      Unified Voice triage consumer, which adds URL keyboard buttons.
      """
      import re as _re
      from services.director_report_service import submit_via_inbox

      # Extract verdict from ai_summary
      verdict = "REVIEWED"
      if ai_summary:
          u = ai_summary.upper()
          if "VERDICT: APPROVE" in u:
              verdict = "APPROVE"
          elif "VERDICT: REQUEST CHANGES" in u:
              verdict = "REQUEST CHANGES"
          elif "VERDICT: NEEDS REVIEW" in u:
              verdict = "NEEDS REVIEW"

      # Extract first 200 chars of summary section
      snippet = ""
      if ai_summary:
          m = _re.search(r"SUMMARY\s*([\s\S]{1,200})", ai_summary, _re.IGNORECASE)
          if m:
              snippet = m.group(1).strip()

      _repo = repo or "KytranKatarn/archie-platform"
      github_url = f"https://github.com/{_repo}/pull/{pr_number}/files"
      platform_url = "http://192.168.1.200:3000/tools/repair-bay#pr-review"

      message = (
          f"VERDICT: {verdict}\n\n"
          f"{snippet}\n\n"
          f"View in Repair Bay: {platform_url}\n"
          f"GitHub PR: {github_url}"
      )

      try:
          submit_via_inbox(
              category="pr_reviewed",
              title=f"F.O.R.G.E. Review: {verdict} — {_repo}#{pr_number}: {title[:60]}",
              message=message,
              source_agent="F.O.R.G.E.",
              severity="info",
              department="Engineering & Technology",
          )
      except Exception as exc:
          logger.warning(
              "[PR Review] Failed to submit Telegram notification for PR #%s: %s",
              pr_number,
              exc,
          )
  ```

- [ ] **Step 3: Wire the call in analyze_pending_prs**

  Find the `mark_review_done(pr_number, summary, repo)` call in `analyze_pending_prs`. Add the notification call immediately after it:

  ```python
                  mark_review_done(pr_number, summary, repo)
                  _notify_pr_reviewed(pr_number, repo, review.get("title", ""), summary)
                  processed += 1
  ```

- [ ] **Step 4: Restart platform and smoke test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  sleep 5
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.pr_diff_analyzer import _notify_pr_reviewed
  print('Import OK')
  "
  ```

  Expected: `Import OK`

- [ ] **Step 5: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py
  git commit -m "feat(pr-review): notify Telegram via inbox when F.O.R.G.E. review completes (#1802)"
  ```

---

## Task 2: Add pr_reviewed keyboard in archie_comms escalation handler

**Files:**
- Modify: `archie-comms/services/telegram_service.py`
- Deploy: `docker compose build archie_comms && docker compose up -d archie_comms`

- [ ] **Step 1: Find the escalation keyboard block**

  ```bash
  grep -n "approval_request\|reply_markup\|inline_keyboard\|category" \
    /mnt/archie_brain/archie-comms/services/telegram_service.py | head -20
  ```

  Find the `if report.get("category") == "approval_request":` block — the new `pr_reviewed` branch goes right after it.

- [ ] **Step 2: Add the pr_reviewed keyboard branch**

  Immediately after the closing block of the `approval_request` keyboard, add:

  ```python
          elif report.get("category") == "pr_reviewed":
              # Extract GitHub PR URL from message body
              _gh_m = _re.search(
                  r"GitHub PR: (https://github\.com/\S+)",
                  report.get("summary", "") or report.get("message", ""),
              )
              if _gh_m:
                  payload["reply_markup"] = {
                      "inline_keyboard": [[
                          {
                              "text": "🔧 View in Repair Bay",
                              "url": "http://192.168.1.200:3000/tools/repair-bay#pr-review",
                          },
                          {
                              "text": "View on GitHub ↗",
                              "url": _gh_m.group(1),
                          },
                      ]]
                  }
  ```

  Note: `_re` is the `re` module — check if it's already imported as `_re` or `re` in this file and use the correct alias.

- [ ] **Step 3: Build and deploy archie_comms**

  ```bash
  cd /mnt/archie_brain && docker compose build archie_comms && docker compose up -d archie_comms
  ```

- [ ] **Step 4: Verify container healthy**

  ```bash
  docker ps --filter "name=archie_comms" --format "{{.Names}}\t{{.Status}}"
  ```

  Expected: `archie_comms   Up X seconds (healthy)`

- [ ] **Step 5: Commit**

  ```bash
  git add archie-comms/services/telegram_service.py
  git commit -m "feat(pr-review): URL keyboard buttons for pr_reviewed Telegram escalation (#1802)"
  ```

---

## Task 3: Insert triage policy for pr_reviewed

**Files:**
- DB migration via docker exec

- [ ] **Step 1: Insert the triage policy**

  ```bash
  docker exec archie_database psql -U archie -d archie -c "
  INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
  VALUES ('info', 'pr_reviewed', 'escalate', 'F.O.R.G.E. PR review completed — notify Kytran', 10, TRUE)
  ON CONFLICT DO NOTHING;
  "
  ```

- [ ] **Step 2: Verify the policy was inserted**

  ```bash
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT id, category_prefix, action, priority, active FROM triage_policies WHERE category_prefix='pr_reviewed';"
  ```

  Expected: one row with `action='escalate'`, `active=true`.

- [ ] **Step 3: Verify triage policy is visible from archie_comms**

  ```bash
  docker exec archie_comms python3 -c "
  from database import get_db_cursor
  with get_db_cursor() as (conn, cur):
      cur.execute(\"SELECT category_prefix, action FROM triage_policies WHERE category_prefix='pr_reviewed'\")
      print(cur.fetchall())
  "
  ```

  Expected: `[('pr_reviewed', 'escalate')]`

- [ ] **Step 4: End-to-end smoke test**

  Insert a fake `pr_reviewed` director_report and confirm it gets escalated:

  ```bash
  docker exec archie_database psql -U archie -d archie -c "
  INSERT INTO director_reports
    (department, director_agent, severity, category, title, summary, triage_status)
  VALUES (
    'Engineering & Technology',
    'F.O.R.G.E.',
    'info',
    'pr_reviewed',
    'F.O.R.G.E. Review: APPROVE — test/repo#1: Test PR',
    E'VERDICT: APPROVE\n\nLooks good.\n\nView in Repair Bay: http://192.168.1.200:3000/tools/repair-bay#pr-review\nGitHub PR: https://github.com/test/repo/pull/1/files',
    'pending'
  )
  RETURNING id;"
  ```

  Wait 35 seconds (triage consumer runs every 30s), then check:

  ```bash
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT id, triage_status, triage_action FROM director_reports WHERE category='pr_reviewed' ORDER BY id DESC LIMIT 1;"
  ```

  Expected: `triage_status='escalated'`, `triage_action='escalate'`.

- [ ] **Step 5: Commit migration note**

  ```bash
  git commit --allow-empty -m "feat(pr-review): triage policy — auto-escalate pr_reviewed category (#1802)"
  ```

---

## Final: PR and Dev HQ

- [ ] **Step 1: Push and open PR**

  ```bash
  git checkout -b feat/pr-review-phase4-1802
  git push -u origin feat/pr-review-phase4-1802
  gh pr create \
    --title "feat(pr-review): Phase 4 — Telegram alerts when F.O.R.G.E. review completes (#1802)" \
    --base main \
    --body "$(cat <<'EOF'
  ## Summary
  - `_notify_pr_reviewed()` called after `mark_review_done()` in pr_diff_analyzer
  - Submits to director_reports inbox with category=pr_reviewed (Unified Voice path)
  - Triage policy auto-escalates pr_reviewed → Telegram
  - archie_comms escalation handler adds URL keyboard: View in Repair Bay + View on GitHub
  - Failure in notification is caught and logged — does not fail the review

  ## Test plan
  - [ ] `_notify_pr_reviewed` importable in container
  - [ ] director_reports row with category=pr_reviewed inserted after review
  - [ ] Triage policy row present in DB
  - [ ] Smoke test: manual insert → escalated after 30s
  - [ ] archie_comms keyboard block present for pr_reviewed

  🤖 Generated with [Claude Code](https://claude.ai/claude-code)
  EOF
  )"
  ```

- [ ] **Step 2: Update Dev HQ**

  ```
  mcp complete_task #1802
  mcp update_project_understanding #247
  ```
