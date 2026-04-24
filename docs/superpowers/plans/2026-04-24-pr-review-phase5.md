# PR Review Phase 5 — Multi-repo + GitHub Presence Audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand PR review to all repos (multi-repo polling), add daily per-repo health checks, and add weekly F.O.R.G.E. GitHub presence audit.

**Architecture:** `get_tracked_repos()` reads `GITHUB_REPOS` env var. Three new agent loop jobs. Two new service files. Two triage policy migrations.

**Tech Stack:** Python, GitHub REST API (GITHUB_TOKEN), APScheduler, Bridge dispatcher, submit_via_inbox, MCP store_memory.

---

## File Map

| File | Action |
|------|--------|
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | Modify — add `get_tracked_repos()` |
| `ai_bridge/agent_loop.py` | Modify — update `_run_pr_review_poll`, add 2 new jobs |
| `platform_v2/tools/repair_bay/services/repo_health_service.py` | Create — health check logic |
| `platform_v2/tools/repair_bay/services/github_presence_service.py` | Create — weekly audit logic |
| `database/migrations/346_triage_policy_repo_health.sql` | Create |
| `database/migrations/347_triage_policy_github_audit.sql` | Create |

---

## Task 1: get_tracked_repos + multi-repo polling

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_review_service.py`
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add get_tracked_repos to pr_review_service.py**

  Append after the existing module-level constants (around line 20, after `_DEFAULT_REPO`):

  ```python
  def get_tracked_repos() -> list:
      """Return the list of repos to poll and audit.

      Reads GITHUB_REPOS (comma-separated). Falls back to GITHUB_REPO for
      backward compatibility with existing single-repo deployments.
      """
      repos_env = os.getenv("GITHUB_REPOS", "").strip()
      if repos_env:
          return [r.strip() for r in repos_env.split(",") if r.strip()]
      return [_DEFAULT_REPO]
  ```

- [ ] **Step 2: Read the current _run_pr_review_poll in agent_loop.py**

  ```bash
  grep -n "_run_pr_review_poll" /mnt/archie_brain/ai_bridge/agent_loop.py
  START=$(grep -n "def _run_pr_review_poll" /mnt/archie_brain/ai_bridge/agent_loop.py | head -1 | cut -d: -f1)
  sed -n "${START},$((START+15))p" /mnt/archie_brain/ai_bridge/agent_loop.py
  ```

- [ ] **Step 3: Update _run_pr_review_poll to loop over all repos**

  Replace the function body with:

  ```python
      def _run_pr_review_poll(self):
          """Poll GitHub for open PRs across all tracked repos (Project #247)."""
          try:
              from tools.repair_bay.services.pr_review_service import (
                  poll_open_prs,
                  sync_closed_prs,
                  get_tracked_repos,
              )

              for repo in get_tracked_repos():
                  result = poll_open_prs(repo=repo)
                  closed = sync_closed_prs(repo=repo)
                  logger.info(
                      "pr_review_poll [%s]: polled=%d inserted=%d updated=%d closed_synced=%d",
                      repo,
                      result.get("polled"),
                      result.get("inserted"),
                      result.get("updated"),
                      closed,
                  )
          except Exception as e:
              logger.error("pr_review_poll failed: %s", e)
  ```

- [ ] **Step 4: Restart and test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  sleep 5
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.pr_review_service import get_tracked_repos
  print('Repos:', get_tracked_repos())
  "
  ```

  Expected: `Repos: ['KytranKatarn/archie-platform']` (or list from env var if set)

- [ ] **Step 5: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/pr_review_service.py \
          ai_bridge/agent_loop.py
  git commit -m "feat(pr-review): multi-repo polling via GITHUB_REPOS env var (#1803)"
  ```

---

## Task 2: repo_health_service + daily health check job

**Files:**
- Create: `platform_v2/tools/repair_bay/services/repo_health_service.py`
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Create repo_health_service.py**

  Create `/mnt/archie_brain/platform_v2/tools/repair_bay/services/repo_health_service.py`:

  ```python
  """Repo Health Service — daily per-repo GitHub presence check.

  Checks each tracked repo for: description, topics, license, README.
  Submits a director_report inbox entry if any are missing.
  """

  from __future__ import annotations

  import logging
  import os

  import requests

  logger = logging.getLogger(__name__)

  _GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
  _GITHUB_API = "https://api.github.com"


  def _gh_headers() -> dict:
      h = {"Accept": "application/vnd.github.v3+json"}
      if _GITHUB_TOKEN:
          h["Authorization"] = f"token {_GITHUB_TOKEN}"
      return h


  def check_repo_health(repo: str) -> dict:
      """Check a single repo for public presence completeness.

      Returns:
          dict: {repo, issues: list[str], healthy: bool}
      """
      issues = []

      try:
          resp = requests.get(
              f"{_GITHUB_API}/repos/{repo}",
              headers=_gh_headers(),
              timeout=15,
          )
          if resp.status_code != 200:
              logger.warning("[RepoHealth] Failed to fetch %s: %s", repo, resp.status_code)
              return {"repo": repo, "issues": [f"API error {resp.status_code}"], "healthy": False}

          data = resp.json()

          if not data.get("description"):
              issues.append("❌ No description set")
          else:
              issues.append("✅ Description present")

          topics = data.get("topics", [])
          if not topics:
              issues.append("❌ No topics tagged")
          else:
              issues.append(f"✅ Topics: {', '.join(topics[:5])}")

          if not data.get("license"):
              issues.append("❌ No license file")
          else:
              issues.append(f"✅ License: {data['license'].get('spdx_id', 'present')}")

      except Exception as exc:
          logger.error("[RepoHealth] Error checking %s: %s", repo, exc)
          return {"repo": repo, "issues": [f"Error: {exc}"], "healthy": False}

      # Check README separately
      try:
          readme_resp = requests.get(
              f"{_GITHUB_API}/repos/{repo}/readme",
              headers=_gh_headers(),
              timeout=10,
          )
          if readme_resp.status_code == 200:
              issues.append("✅ README present")
          else:
              issues.append("❌ No README found")
      except Exception as exc:
          issues.append(f"❌ README check failed: {exc}")

      problem_lines = [l for l in issues if l.startswith("❌")]
      healthy = len(problem_lines) == 0

      return {"repo": repo, "issues": issues, "healthy": healthy}


  def run_health_checks() -> dict:
      """Run health check for all tracked repos. Submit inbox report for any unhealthy repo.

      Returns:
          dict: {checked, unhealthy, healthy}
      """
      from tools.repair_bay.services.pr_review_service import get_tracked_repos
      from services.director_report_service import submit_via_inbox

      repos = get_tracked_repos()
      healthy_count = unhealthy_count = 0

      for repo in repos:
          result = check_repo_health(repo)
          if result["healthy"]:
              logger.info("[RepoHealth] %s — all clear", repo)
              healthy_count += 1
          else:
              unhealthy_count += 1
              problem_lines = [l for l in result["issues"] if l.startswith("❌")]
              message = (
                  f"Repo: {repo}\n\n"
                  + "\n".join(result["issues"])
                  + f"\n\nView: https://github.com/{repo}"
              )
              try:
                  submit_via_inbox(
                      category="repo_health",
                      title=f"Repo Health: {len(problem_lines)} issue(s) — {repo}",
                      message=message,
                      source_agent="F.O.R.G.E.",
                      severity="warning",
                      department="Engineering & Technology",
                  )
                  logger.info("[RepoHealth] %s — %d issues, reported to inbox", repo, len(problem_lines))
              except Exception as exc:
                  logger.error("[RepoHealth] Failed to submit inbox report for %s: %s", repo, exc)

      return {"checked": len(repos), "healthy": healthy_count, "unhealthy": unhealthy_count}
  ```

- [ ] **Step 2: Add the daily health check job to agent_loop.py**

  Find where `forge_pr_diff_analysis` job is registered. Add immediately after it:

  ```python
          # Daily repo health check — inspects README/description/topics/license for each tracked repo.
          APScheduler.add_job(
              with_app_context(self._run_repo_health_check),
              "cron",
              hour=6,
              minute=0,
              id="forge_repo_health_check",
              max_instances=1,
              coalesce=True,
          )
  ```

  Then add the method after `_run_pr_diff_analysis`:

  ```python
      def _run_repo_health_check(self):
          """Daily per-repo GitHub presence health check (Project #247, Task #1803)."""
          try:
              from tools.repair_bay.services.repo_health_service import run_health_checks

              result = run_health_checks()
              logger.info(
                  "repo_health_check: checked=%d healthy=%d unhealthy=%d",
                  result.get("checked"),
                  result.get("healthy"),
                  result.get("unhealthy"),
              )
          except Exception as e:
              logger.error("repo_health_check failed: %s", e)
  ```

- [ ] **Step 3: Restart and smoke test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  sleep 5
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.repo_health_service import check_repo_health
  result = check_repo_health('KytranKatarn/archie-platform')
  print('Healthy:', result['healthy'])
  for issue in result['issues']:
      print(' ', issue)
  "
  ```

  Expected: list of ✅/❌ lines for the archie-platform repo.

- [ ] **Step 4: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/repo_health_service.py \
          ai_bridge/agent_loop.py
  git commit -m "feat(pr-review): daily repo health check job — README/description/topics/license (#1803)"
  ```

---

## Task 3: DB migrations for triage policies

**Files:**
- Create: `database/migrations/346_triage_policy_repo_health.sql`
- Create: `database/migrations/347_triage_policy_github_audit.sql`

- [ ] **Step 1: Find next migration number**

  ```bash
  ls /mnt/archie_brain/database/migrations/ | sort | tail -3
  ```

  Use the next available number after the last file (should be 346 and 347 based on 345 being last).

- [ ] **Step 2: Create 346_triage_policy_repo_health.sql**

  ```sql
  -- Migration: Triage policy — escalate repo_health director_reports
  INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
  SELECT 'warning', 'repo_health', 'escalate',
         'Repo missing README/description/topics/license — notify Kytran', 5, TRUE
  WHERE NOT EXISTS (
      SELECT 1 FROM triage_policies WHERE category_prefix = 'repo_health'
  );
  ```

- [ ] **Step 3: Create 347_triage_policy_github_audit.sql**

  ```sql
  -- Migration: Triage policy — escalate github_audit director_reports
  INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
  SELECT 'info', 'github_audit', 'escalate',
         'Weekly F.O.R.G.E. GitHub presence audit — notify Kytran', 5, TRUE
  WHERE NOT EXISTS (
      SELECT 1 FROM triage_policies WHERE category_prefix = 'github_audit'
  );
  ```

- [ ] **Step 4: Run both migrations**

  ```bash
  docker exec archie_database psql -U archie -d archie \
    -f /mnt/archie_brain/database/migrations/346_triage_policy_repo_health.sql
  docker exec archie_database psql -U archie -d archie \
    -f /mnt/archie_brain/database/migrations/347_triage_policy_github_audit.sql
  ```

- [ ] **Step 5: Verify both rows**

  ```bash
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT category_prefix, action, priority, active FROM triage_policies WHERE category_prefix IN ('repo_health','github_audit') ORDER BY category_prefix;"
  ```

  Expected: 2 rows.

- [ ] **Step 6: Commit**

  ```bash
  git add database/migrations/346_triage_policy_repo_health.sql \
          database/migrations/347_triage_policy_github_audit.sql
  git commit -m "migration: triage policies for repo_health + github_audit categories (#1803)"
  ```

---

## Task 4: github_presence_service + weekly audit job

**Files:**
- Create: `platform_v2/tools/repair_bay/services/github_presence_service.py`
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Create github_presence_service.py**

  Create `/mnt/archie_brain/platform_v2/tools/repair_bay/services/github_presence_service.py`:

  ```python
  """GitHub Presence Service — weekly F.O.R.G.E. audit of KytranKatarn public profile.

  Fetches all public repos, dispatches to F.O.R.G.E. for quality analysis,
  stores result in KB vault_note and sends via inbox.
  """

  from __future__ import annotations

  import logging
  import os
  from datetime import datetime

  import requests

  logger = logging.getLogger(__name__)

  _GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
  _GITHUB_ORG = os.getenv("GITHUB_ORG", "KytranKatarn")
  _GITHUB_API = "https://api.github.com"


  def _gh_headers() -> dict:
      h = {"Accept": "application/vnd.github.v3+json"}
      if _GITHUB_TOKEN:
          h["Authorization"] = f"token {_GITHUB_TOKEN}"
      return h


  def fetch_public_repos() -> list:
      """Fetch all public repos for the GitHub org/user."""
      repos = []
      page = 1
      while True:
          resp = requests.get(
              f"{_GITHUB_API}/users/{_GITHUB_ORG}/repos",
              headers=_gh_headers(),
              params={"type": "public", "per_page": 100, "page": page},
              timeout=15,
          )
          if resp.status_code != 200:
              logger.error("[GitHubPresence] Failed to fetch repos: %s", resp.status_code)
              break
          batch = resp.json()
          if not batch:
              break
          repos.extend(batch)
          if len(batch) < 100:
              break
          page += 1
      return repos


  def run_presence_audit() -> dict:
      """Fetch public repos, dispatch to F.O.R.G.E., store in KB and inbox.

      Returns:
          dict: {repo_count, summary_length, success}
      """
      from tools.department_hq.services.department_dispatcher import dispatch
      from services.director_report_service import submit_via_inbox

      repos = fetch_public_repos()
      if not repos:
          logger.warning("[GitHubPresence] No public repos found for %s", _GITHUB_ORG)
          return {"repo_count": 0, "success": False}

      # Build compact repo summary
      lines = []
      for r in repos:
          topics = ", ".join(r.get("topics", [])[:3]) or "none"
          desc = (r.get("description") or "no description")[:60]
          lines.append(
              f"- {r['name']}: {desc} | stars={r.get('stargazers_count',0)} "
              f"| updated={r.get('updated_at','?')[:10]} | topics={topics}"
          )

      repo_summary = "\n".join(lines)
      today = datetime.utcnow().strftime("%Y-%m-%d")

      prompt = (
          f"You are F.O.R.G.E., reviewing the public GitHub profile of {_GITHUB_ORG}.\n\n"
          f"Public repos ({len(repos)} total):\n{repo_summary}\n\n"
          f"Provide your assessment in this exact format:\n\n"
          f"SUMMARY\n"
          f"2-3 sentences on overall GitHub public presence quality.\n\n"
          f"ISSUES\n"
          f"- [HIGH/MEDIUM/LOW] <issue> — <specific recommendation>\n"
          f"(List only real issues. If presence is strong, write: No significant issues.)\n\n"
          f"VERDICT: PROFESSIONAL | NEEDS IMPROVEMENT | URGENT ACTION NEEDED"
      )

      try:
          result = dispatch(
              capability="code_review",
              prompt=prompt,
              module_id="repair_bay",
          )
          analysis = result.response.strip() if result.success and result.response else None
      except Exception as exc:
          logger.error("[GitHubPresence] F.O.R.G.E. dispatch failed: %s", exc)
          return {"repo_count": len(repos), "success": False}

      if not analysis:
          logger.warning("[GitHubPresence] F.O.R.G.E. returned empty response")
          return {"repo_count": len(repos), "success": False}

      # Store in knowledge base — use get_db_cursor to insert into knowledge_base table directly
      # (Check `platform_v2/services/knowledge_service.py` for the canonical helper if available)
      try:
          from database import get_db_cursor
          with get_db_cursor(commit=True) as (conn, cur):
              cur.execute(
                  """
                  INSERT INTO knowledge_base
                    (title, content, knowledge_type, category, importance_score, has_embedding)
                  VALUES (%s, %s, 'vault_note', 'github_presence', 0.75, FALSE)
                  """,
                  (
                      f"GitHub Presence Audit — {today}",
                      f"# GitHub Presence Audit — {today}\n\nRepos: {len(repos)}\n\n{analysis}",
                  ),
              )
          logger.info("[GitHubPresence] Stored audit in KB vault_note")
      except Exception as exc:
          logger.warning("[GitHubPresence] Failed to store in KB: %s", exc)

      # Send to inbox
      try:
          submit_via_inbox(
              category="github_audit",
              title=f"F.O.R.G.E. GitHub Presence Audit — {today} ({len(repos)} repos)",
              message=analysis,
              source_agent="F.O.R.G.E.",
              severity="info",
              department="Engineering & Technology",
          )
      except Exception as exc:
          logger.warning("[GitHubPresence] Failed to submit to inbox: %s", exc)

      return {"repo_count": len(repos), "summary_length": len(analysis), "success": True}
  ```

- [ ] **Step 2: Add weekly audit job to agent_loop.py**

  Add after the `forge_repo_health_check` job registration:

  ```python
          # Weekly GitHub public presence audit via F.O.R.G.E.
          APScheduler.add_job(
              with_app_context(self._run_github_presence_audit),
              "cron",
              day_of_week="sun",
              hour=3,
              minute=0,
              id="forge_github_presence_audit",
              max_instances=1,
              coalesce=True,
          )
  ```

  Add the method after `_run_repo_health_check`:

  ```python
      def _run_github_presence_audit(self):
          """Weekly F.O.R.G.E. audit of KytranKatarn GitHub public presence (Project #247, Task #1803)."""
          try:
              from tools.repair_bay.services.github_presence_service import run_presence_audit

              result = run_presence_audit()
              logger.info(
                  "github_presence_audit: repos=%d success=%s",
                  result.get("repo_count"),
                  result.get("success"),
              )
          except Exception as e:
              logger.error("github_presence_audit failed: %s", e)
  ```

- [ ] **Step 3: Restart and smoke test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  sleep 5
  docker exec archie_platform python3 -c "
  from tools.repair_bay.services.github_presence_service import fetch_public_repos
  repos = fetch_public_repos()
  print(f'Found {len(repos)} public repos')
  for r in repos[:3]:
      print(f'  - {r[\"name\"]}: {r.get(\"description\", \"no desc\")[:50]}')
  "
  ```

  Expected: lists real public repos from KytranKatarn.

- [ ] **Step 4: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/services/github_presence_service.py \
          ai_bridge/agent_loop.py
  git commit -m "feat(pr-review): weekly F.O.R.G.E. GitHub presence audit job (#1803)"
  ```

---

## Final: PR and Dev HQ

- [ ] **Step 1: Push and open PR**

  ```bash
  git push -u origin feat/pr-review-phase5-1803
  gh pr create \
    --title "feat(pr-review): Phase 5 — Multi-repo + GitHub Presence Audit (#1803)" \
    --base main \
    --body "$(cat <<'EOF'
  ## Summary

  **B — Multi-repo polling:**
  - `get_tracked_repos()` reads `GITHUB_REPOS` env var (comma-separated), falls back to `GITHUB_REPO`
  - `_run_pr_review_poll` loops over all repos

  **A — Daily repo health check:**
  - `repo_health_service.py` checks README, description, topics, license via GitHub API
  - Daily at 06:00 UTC, unhealthy repos trigger inbox entry with `category=repo_health`
  - Migration `346_triage_policy_repo_health.sql`

  **C — Weekly GitHub presence audit:**
  - `github_presence_service.py` fetches all public repos, dispatches to F.O.R.G.E.
  - Weekly Sunday 03:00 UTC, result stored in KB vault_note + inbox
  - Migration `347_triage_policy_github_audit.sql`

  ## Test plan
  - [ ] `get_tracked_repos()` returns correct repos from env
  - [ ] `check_repo_health('KytranKatarn/archie-platform')` returns ✅/❌ lines
  - [ ] `fetch_public_repos()` returns real repos
  - [ ] Both triage policy rows in DB
  - [ ] Both jobs registered in scheduler

  🤖 Generated with [Claude Code](https://claude.ai/claude-code)
  EOF
  )"
  ```

- [ ] **Step 2: Update Dev HQ**

  ```
  mcp complete_task #1803
  mcp update_project_understanding #247
  ```
