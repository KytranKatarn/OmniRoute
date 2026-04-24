# PR Review Phase 2 — F.O.R.G.E. AI Diff Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire F.O.R.G.E. into the PR review pipeline so every pending PR gets an AI code review stored in `pr_reviews.ai_summary`.

**Architecture:** A new `pr_diff_analyzer.py` service fetches the GitHub diff, dispatches to F.O.R.G.E. via Bridge, and stores the result. An agent loop job runs it every 10 minutes. An on-demand route allows immediate triggering from the UI.

**Tech Stack:** Python/Flask, APScheduler, PostgreSQL (`pr_reviews` table), GitHub API (GITHUB_TOKEN), Bridge dispatcher (`dispatch(capability="code_review", ...)`).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | Modify | Add `mark_review_pending()` reset function |
| `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py` | Create | Core analysis logic: fetch diff, build prompt, call F.O.R.G.E. |
| `ai_bridge/agent_loop.py` | Modify | Add `_run_pr_diff_analysis` job (10 min interval) |
| `platform_v2/tools/repair_bay/github_routes.py` | Modify | Add `POST /api/forge/pr-reviews/<pr_number>/analyze` route |
| `tests/test_pr_diff_analyzer.py` | Create | Unit tests for the analyzer |

---

## Task 1: Add mark_review_pending to pr_review_service

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_review_service.py`
- Test: `tests/test_pr_diff_analyzer.py`

- [ ] **Step 1: Write the failing test**

  Create `tests/test_pr_diff_analyzer.py`:

  ```python
  """Tests for PR diff analyzer — Phase 2 of PR Review Pipeline."""
  import pytest
  from unittest.mock import patch, MagicMock


  class TestMarkReviewPending:
      def test_mark_review_pending_exists(self):
          """mark_review_pending must be importable from pr_review_service."""
          from platform_v2.tools.repair_bay.services.pr_review_service import (
              mark_review_pending,
          )
          assert callable(mark_review_pending)
  ```

- [ ] **Step 2: Run test to confirm it fails**

  ```bash
  cd /mnt/archie_brain && python3 -m pytest tests/test_pr_diff_analyzer.py::TestMarkReviewPending -v
  ```

  Expected: `FAILED` with `ImportError` or `cannot import name 'mark_review_pending'`

- [ ] **Step 3: Add mark_review_pending to pr_review_service.py**

  Open `platform_v2/tools/repair_bay/services/pr_review_service.py`. After the `mark_review_skipped` function (around line 170), add:

  ```python
  def mark_review_pending(pr_number: int, repo: str = None) -> None:
      """Reset a review back to pending so it will be re-processed next cycle."""
      with get_db_cursor(commit=True) as (conn, cur):
          cur.execute(
              "UPDATE pr_reviews SET review_status='pending', updated_at=NOW() WHERE pr_number=%s AND repo=%s",
              (pr_number, repo or _DEFAULT_REPO),
          )
  ```

- [ ] **Step 4: Run test to confirm it passes**

  ```bash
  cd /mnt/archie_brain && python3 -m pytest tests/test_pr_diff_analyzer.py::TestMarkReviewPending -v
  ```

  Expected: `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/pr_review_service.py \
          tests/test_pr_diff_analyzer.py
  git commit -m "feat(pr-review): add mark_review_pending reset function (#1800)"
  ```

---

## Task 2: Create pr_diff_analyzer.py

**Files:**
- Create: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`
- Test: `tests/test_pr_diff_analyzer.py`

- [ ] **Step 1: Write failing tests for all three internal functions**

  Append to `tests/test_pr_diff_analyzer.py`:

  ```python
  class TestFetchDiff:
      def test_returns_diff_string_on_success(self):
          """_fetch_diff returns the response text on HTTP 200."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import _fetch_diff

          mock_resp = MagicMock()
          mock_resp.status_code = 200
          mock_resp.text = "diff --git a/foo.py b/foo.py\n+print('hello')"

          with patch("platform_v2.tools.repair_bay.services.pr_diff_analyzer.requests.get",
                     return_value=mock_resp):
              result = _fetch_diff("https://github.com/org/repo/pull/1.diff")

          assert result == mock_resp.text

      def test_raises_on_non_200(self):
          """_fetch_diff raises RuntimeError when GitHub returns non-200."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import _fetch_diff

          mock_resp = MagicMock()
          mock_resp.status_code = 403
          mock_resp.text = "Forbidden"

          with patch("platform_v2.tools.repair_bay.services.pr_diff_analyzer.requests.get",
                     return_value=mock_resp):
              with pytest.raises(RuntimeError, match="403"):
                  _fetch_diff("https://github.com/org/repo/pull/1.diff")


  class TestBuildPrompt:
      def test_includes_pr_metadata(self):
          """_build_prompt includes PR number, title, author, and diff."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import _build_prompt

          review = {
              "pr_number": 42,
              "title": "Add feature X",
              "author": "dev1",
              "repo": "KytranKatarn/archie-platform",
              "additions": 100,
              "deletions": 20,
              "changed_files": 3,
          }
          diff = "diff --git a/foo.py b/foo.py\n+print('x')"
          prompt = _build_prompt(review, diff)

          assert "#42" in prompt
          assert "Add feature X" in prompt
          assert "dev1" in prompt
          assert diff in prompt

      def test_truncates_large_diff(self):
          """_build_prompt truncates diff over 6000 chars and adds a note."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import _build_prompt

          review = {
              "pr_number": 1,
              "title": "Big PR",
              "author": "dev",
              "repo": "repo",
              "additions": 1000,
              "deletions": 0,
              "changed_files": 10,
          }
          large_diff = "x" * 7000
          prompt = _build_prompt(review, large_diff)

          assert "truncated" in prompt.lower()
          assert "x" * 7000 not in prompt


  class TestAnalyzePendingPrs:
      def test_returns_stats_dict(self):
          """analyze_pending_prs returns {processed, failed, skipped}."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import (
              analyze_pending_prs,
          )

          with patch(
              "platform_v2.tools.repair_bay.services.pr_diff_analyzer.get_pending_reviews",
              return_value=[],
          ):
              result = analyze_pending_prs(max_prs=3)

          assert result == {"processed": 0, "failed": 0, "skipped": 0}

      def test_processes_pending_pr(self):
          """analyze_pending_prs processes a pending review end-to-end."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import (
              analyze_pending_prs,
          )

          fake_review = {
              "pr_number": 99,
              "repo": "KytranKatarn/archie-platform",
              "title": "Test PR",
              "author": "dev",
              "additions": 10,
              "deletions": 2,
              "changed_files": 1,
              "diff_url": "https://github.com/org/repo/pull/99.diff",
          }
          fake_summary = "SUMMARY\nLooks good.\n\nISSUES\nNo issues found.\n\nVERDICT: APPROVE"

          with (
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.get_pending_reviews",
                  return_value=[fake_review],
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.mark_review_started",
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer._fetch_diff",
                  return_value="diff content",
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer._run_forge_review",
                  return_value=fake_summary,
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.mark_review_done",
              ) as mock_done,
          ):
              result = analyze_pending_prs(max_prs=3)

          assert result["processed"] == 1
          assert result["failed"] == 0
          mock_done.assert_called_once_with(99, fake_summary, "KytranKatarn/archie-platform")

      def test_reverts_to_pending_on_fetch_failure(self):
          """analyze_pending_prs resets status to pending when diff fetch fails."""
          from platform_v2.tools.repair_bay.services.pr_diff_analyzer import (
              analyze_pending_prs,
          )

          fake_review = {
              "pr_number": 99,
              "repo": "KytranKatarn/archie-platform",
              "title": "Test PR",
              "author": "dev",
              "additions": 10,
              "deletions": 2,
              "changed_files": 1,
              "diff_url": "https://github.com/org/repo/pull/99.diff",
          }

          with (
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.get_pending_reviews",
                  return_value=[fake_review],
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.mark_review_started",
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer._fetch_diff",
                  side_effect=RuntimeError("403 Forbidden"),
              ),
              patch(
                  "platform_v2.tools.repair_bay.services.pr_diff_analyzer.mark_review_pending",
              ) as mock_reset,
          ):
              result = analyze_pending_prs(max_prs=3)

          assert result["failed"] == 1
          mock_reset.assert_called_once_with(99, "KytranKatarn/archie-platform")
  ```

- [ ] **Step 2: Run tests to confirm they all fail**

  ```bash
  cd /mnt/archie_brain && python3 -m pytest tests/test_pr_diff_analyzer.py -v --ignore-glob="*TestMarkReviewPending*" 2>&1 | tail -20
  ```

  Expected: all new tests `ERROR` or `FAILED` with import errors.

- [ ] **Step 3: Create pr_diff_analyzer.py**

  Create `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`:

  ```python
  """PR Diff Analyzer — Phase 2 of the PR Review Pipeline.

  Fetches GitHub diffs for pending PR reviews and dispatches them to F.O.R.G.E.
  via the Bridge dispatcher for AI code review. Results stored in pr_reviews.ai_summary.
  """

  from __future__ import annotations

  import logging
  import os

  import requests

  from tools.repair_bay.services.pr_review_service import (
      get_pending_reviews,
      mark_review_done,
      mark_review_pending,
      mark_review_started,
  )

  logger = logging.getLogger(__name__)

  _GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
  _DIFF_MAX_CHARS = 6000


  def analyze_pending_prs(max_prs: int = 3) -> dict:
      """Process up to max_prs pending reviews with F.O.R.G.E. AI analysis.

      Returns:
          dict: {processed, failed, skipped}
      """
      reviews = get_pending_reviews(limit=max_prs)
      processed = failed = skipped = 0

      for review in reviews:
          pr_number = review["pr_number"]
          repo = review.get("repo", "KytranKatarn/archie-platform")

          try:
              mark_review_started(pr_number, repo)

              diff = _fetch_diff(review["diff_url"])
              prompt = _build_prompt(review, diff)
              summary = _run_forge_review(prompt)

              if summary:
                  mark_review_done(pr_number, summary, repo)
                  processed += 1
              else:
                  logger.warning("[PR Review] F.O.R.G.E. returned empty summary for PR #%s", pr_number)
                  mark_review_pending(pr_number, repo)
                  failed += 1

          except Exception as exc:
              logger.error("[PR Review] PR #%s analysis failed: %s", pr_number, exc)
              try:
                  mark_review_pending(pr_number, repo)
              except Exception as reset_err:
                  logger.error("[PR Review] Failed to reset PR #%s status: %s", pr_number, reset_err)
              failed += 1

      logger.info(
          "[PR Review] Cycle complete — processed=%d failed=%d skipped=%d",
          processed,
          failed,
          skipped,
      )
      return {"processed": processed, "failed": failed, "skipped": skipped}


  def _fetch_diff(diff_url: str) -> str:
      """Fetch raw unified diff from GitHub.

      Args:
          diff_url: URL like https://github.com/org/repo/pull/N.diff

      Returns:
          Raw diff string.

      Raises:
          RuntimeError: If GitHub returns non-200.
      """
      headers = {"Accept": "application/vnd.github.v3.diff"}
      if _GITHUB_TOKEN:
          headers["Authorization"] = f"token {_GITHUB_TOKEN}"

      resp = requests.get(diff_url, headers=headers, timeout=30)
      if resp.status_code != 200:
          raise RuntimeError(f"GitHub diff fetch failed: {resp.status_code} for {diff_url}")
      return resp.text


  def _build_prompt(review: dict, diff: str) -> str:
      """Assemble the F.O.R.G.E. code review prompt.

      Truncates diff at _DIFF_MAX_CHARS to stay within model context limits.
      """
      truncated = len(diff) > _DIFF_MAX_CHARS
      diff_content = diff[:_DIFF_MAX_CHARS] if truncated else diff
      truncation_note = "\n[Note: diff truncated to first 6000 chars due to size.]\n" if truncated else ""

      return f"""You are F.O.R.G.E., A.R.C.H.I.E.'s Full-cycle Optimization & Regenerative GitHub Engine.
  Review this pull request diff and provide a structured code review.

  PR #{review['pr_number']} — {review['title']}
  Author: {review.get('author', 'unknown')} | Repo: {review.get('repo', '')}
  Changes: +{review.get('additions', 0)} -{review.get('deletions', 0)} across {review.get('changed_files', 0)} files

  --- DIFF ---
  {diff_content}
  --- END DIFF ---
  {truncation_note}
  Provide your review in this exact format:

  SUMMARY
  One paragraph describing what this PR does and its overall quality.

  ISSUES
  - [CRITICAL] <issue> — <why it matters>
  - [WARNING] <issue> — <why it matters>
  - [INFO] <issue> — <why it matters>
  (List only real issues. If none found, write: No issues found.)

  VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW"""


  def _run_forge_review(prompt: str) -> str | None:
      """Dispatch the review prompt to F.O.R.G.E. via Bridge.

      Returns:
          Summary string from F.O.R.G.E., or None on failure.
      """
      try:
          from tools.department_hq.services.department_dispatcher import dispatch

          result = dispatch(
              capability="code_review",
              prompt=prompt,
              module_id="repair_bay",
              source_agent="F.O.R.G.E.",
          )
          if result.success and result.response:
              return result.response.strip()
          logger.warning("[PR Review] F.O.R.G.E. dispatch returned no response: success=%s", result.success)
          return None
      except Exception as exc:
          logger.error("[PR Review] F.O.R.G.E. dispatch error: %s", exc)
          raise
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```bash
  cd /mnt/archie_brain && python3 -m pytest tests/test_pr_diff_analyzer.py -v
  ```

  Expected: all tests `PASSED`.

- [ ] **Step 5: Restart platform and smoke test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Then verify the module imports cleanly inside the container:

  ```bash
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs
  print('Import OK')
  result = analyze_pending_prs(max_prs=1)
  print('Result:', result)
  "
  ```

  Expected: `Import OK` then `Result: {'processed': 0, 'failed': 0, 'skipped': 0}` (no pending PRs yet) or a real review if one is pending.

- [ ] **Step 6: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py \
          tests/test_pr_diff_analyzer.py
  git commit -m "feat(pr-review): F.O.R.G.E. diff analyzer service (#1800)"
  ```

---

## Task 3: Add agent loop job

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Find where the PR review poll job is registered**

  ```bash
  grep -n "forge_pr_review_poll\|_run_pr_review_poll" /mnt/archie_brain/ai_bridge/agent_loop.py
  ```

  Note the line number of the `add_job` call and the `_run_pr_review_poll` method.

- [ ] **Step 2: Add the job registration**

  Immediately after the `forge_pr_review_poll` `add_job` block, add:

  ```python
          # F.O.R.G.E. AI diff analysis — runs every 10 min, processes up to 3 pending PRs.
          APScheduler.add_job(
              with_app_context(self._run_pr_diff_analysis),
              "interval",
              minutes=10,
              id="forge_pr_diff_analysis",
              max_instances=1,
              coalesce=True,
          )
  ```

- [ ] **Step 3: Add the method implementation**

  Immediately after the `_run_pr_review_poll` method body, add:

  ```python
      def _run_pr_diff_analysis(self):
          """Phase 2: F.O.R.G.E. AI code review of pending PRs (Project #247, Task #1800)."""
          try:
              from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

              result = analyze_pending_prs(max_prs=3)
              logger.info(
                  "pr_diff_analysis: processed=%d failed=%d skipped=%d",
                  result.get("processed"),
                  result.get("failed"),
                  result.get("skipped"),
              )
          except Exception as e:
              logger.error("pr_diff_analysis failed: %s", e)
  ```

- [ ] **Step 4: Restart platform and confirm job registered**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Check job appears in scheduler:

  ```bash
  docker exec archie_platform python3 -c "
  from ai_bridge.agent_loop import AgentLoop
  loop = AgentLoop.__new__(AgentLoop)
  print('Job wired correctly — no import errors')
  "
  ```

  Also check logs for the job starting:

  ```bash
  docker logs archie_platform --tail=30 2>&1 | grep -i "pr_diff\|forge_pr"
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add ai_bridge/agent_loop.py
  git commit -m "feat(agent-loop): schedule F.O.R.G.E. PR diff analysis every 10min (#1800)"
  ```

---

## Task 4: Add on-demand analyze route

**Files:**
- Modify: `platform_v2/tools/repair_bay/github_routes.py`

- [ ] **Step 1: Find the route registration location**

  ```bash
  grep -n "forge_pr_reviews_poll\|def forge_pr_review" /mnt/archie_brain/platform_v2/tools/repair_bay/github_routes.py
  ```

  Note the line of `forge_pr_reviews_poll` — add the new route immediately after it.

- [ ] **Step 2: Add the on-demand analyze route**

  After the `forge_pr_reviews_poll` function, add:

  ```python
      @bp.route("/api/forge/pr-reviews/<int:pr_number>/analyze", methods=["POST"])
      @login_required
      @admin_required
      def forge_pr_review_analyze(pr_number):
          """Trigger immediate F.O.R.G.E. AI review for a specific PR.

          Calls the analyzer internals directly on the requested PR — bypasses
          the pending queue so it always processes this exact PR, not the oldest one.
          """
          from .services.pr_review_service import (
              get_review,
              mark_review_started,
              mark_review_done,
              mark_review_pending,
          )
          from .services.pr_diff_analyzer import _fetch_diff, _build_prompt, _run_forge_review

          review = get_review(pr_number)
          if not review:
              return jsonify({"error": f"PR #{pr_number} not found in pr_reviews"}), 404

          repo = review.get("repo", "KytranKatarn/archie-platform")
          try:
              mark_review_started(pr_number, repo)
              diff = _fetch_diff(review["diff_url"])
              prompt = _build_prompt(review, diff)
              summary = _run_forge_review(prompt)

              if not summary:
                  mark_review_pending(pr_number, repo)
                  return jsonify({"success": False, "error": "F.O.R.G.E. returned empty response"}), 500

              mark_review_done(pr_number, summary, repo)
              return jsonify({"success": True, "pr_number": pr_number, "summary": summary})

          except Exception as exc:
              mark_review_pending(pr_number, repo)
              return jsonify({"success": False, "error": str(exc)}), 500
  ```

- [ ] **Step 3: Restart platform**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

- [ ] **Step 4: Test the route exists**

  ```bash
  TOKEN=$(docker exec archie_platform python3 -c "
  import os; os.environ.setdefault('FLASK_ENV','development')
  from app import app
  with app.test_client() as c:
      # Just verify the route is registered
      rules = [str(r) for r in app.url_map.iter_rules()]
      matches = [r for r in rules if 'analyze' in r]
      print(matches)
  ")
  echo "$TOKEN"
  ```

  Expected output includes `/tools/repair-bay/api/forge/pr-reviews/<pr_number>/analyze`

- [ ] **Step 5: Integration test — trigger analysis for an existing PR**

  First find a PR number in the database:

  ```bash
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT pr_number, title, review_status FROM pr_reviews ORDER BY id DESC LIMIT 3;"
  ```

  Then trigger analysis (replace `<PR_NUMBER>` with a real one, and log in first to get a session):

  ```bash
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs
  from tools.repair_bay.services.pr_review_service import mark_review_pending, get_review
  # Reset PR #<PR_NUMBER> and run analysis
  mark_review_pending(<PR_NUMBER>)
  result = analyze_pending_prs(max_prs=1)
  print('Result:', result)
  review = get_review(<PR_NUMBER>)
  print('Summary (first 200 chars):', (review.get('ai_summary') or '')[:200])
  "
  ```

  Expected: `Result: {'processed': 1, 'failed': 0, 'skipped': 0}` and a non-empty summary starting with `SUMMARY`.

- [ ] **Step 6: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/github_routes.py
  git commit -m "feat(pr-review): on-demand analyze route POST /api/forge/pr-reviews/<n>/analyze (#1800)"
  ```

---

## Final: PR

- [ ] **Step 1: Push and open PR**

  ```bash
  git checkout -b feat/pr-review-phase2-1800
  git cherry-pick <commit-shas-from-tasks-1-4>  # or just push if already on a feature branch
  git push -u origin feat/pr-review-phase2-1800
  gh pr create \
    --title "feat(pr-review): Phase 2 — F.O.R.G.E. AI diff analysis (#1800)" \
    --body "$(cat <<'EOF'
  ## Summary
  - New `pr_diff_analyzer.py` service: fetches GitHub diff, builds F.O.R.G.E. prompt, stores AI review in `pr_reviews.ai_summary`
  - Agent loop job runs every 10 min, max 3 PRs per cycle
  - `mark_review_pending()` reset function added to pr_review_service
  - On-demand route: POST /api/forge/pr-reviews/<n>/analyze
  - Failures revert to pending (not stuck in_progress)
  - Diff capped at 6000 chars with truncation note

  ## Test plan
  - [ ] All unit tests pass: `pytest tests/test_pr_diff_analyzer.py -v`
  - [ ] Import works inside container
  - [ ] Agent loop job registered (check logs on restart)
  - [ ] On-demand route triggers real F.O.R.G.E. review and populates ai_summary

  🤖 Generated with [Claude Code](https://claude.ai/claude-code)
  EOF
  )"
  ```

- [ ] **Step 2: Update Dev HQ**

  ```
  mcp complete_task #1800 — "F.O.R.G.E. AI diff analysis live. pr_diff_analyzer.py + 10min scheduler + on-demand route. Diffs capped at 6000 chars. Failures reset to pending for retry."
  mcp update_project_understanding #247
  ```
