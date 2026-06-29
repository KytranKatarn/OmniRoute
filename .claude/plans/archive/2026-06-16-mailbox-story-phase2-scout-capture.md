# Mailbox Story — Phase 2: S.C.O.U.T. autonomous chat-share capture

**Status:** designed, NOT built. #1730 (chat→Mailbox Story ingestion) is merged on `main`.
Investigation complete; this is a clean pickup for a fresh session.

## Goal
A.R.C.H.I.E. agents (S.C.O.U.T.) capture a public AI chat **share link** server-side —
render it, scroll-until-stable, extract the transcript — and land it in Mailbox Story via
the existing `mailbox_chat_service.ingest_chat(title, messages, owner_id)`. No new dispatch
path; capture/parse is deterministic, then the existing enrich worker (DHQ
`capability='analyze', local_only=True`) processes the rows.

> Share links are frozen SNAPSHOTS — they only contain what was visible when shared.
> For COMPLETE history the export path (`ingest_export_file`, already shipped) is still the
> source of truth. This Phase 2 is the convenience/autonomous path for a single shared thread.

## How the scraper works (verified)
- `archie-scraper/` is an HTTP service (`archie_scraper:4243`, docker-compose ~L1071,
  build `./archie-scraper`, image-baked → **rebuild required** for changes).
- Skills live in `archie-scraper/skills/*.py`; each exposes `def run(page, params, ...)` and
  gets a live Playwright `page`. `crm_enrich.py` uses `page.evaluate(...)` → **skills CAN run
  custom extraction JS**. Pattern returns `{"data": {...}, "screenshots": [...], ...}`.
- Platform invokes a skill via `browser_service.run_skill_sync(skill_name, params,
  agent_id=_SCRAPE_AGENT_ID, timeout_s=...)` (browser_service.py L59; `scrape_article` L277 is
  the reference caller).

## Build steps
1. **New scraper skill** `archie-scraper/skills/chat_capture.py`:
   - `run(page, params)`: `page.goto(params["url"], wait_until="networkidle")`.
   - Scroll-until-stable loop (mirror the `chat-capture` SKILL.md Mode A): repeatedly
     `page.mouse.wheel`/`scrollTo(0, document.body.scrollHeight)` until message count stops
     growing for N stable iterations or a cap (~60 iters).
   - Extract via `page.evaluate`: ChatGPT shares use `[data-message-author-role]`
     (role = attr value, text = `.innerText`); fall back to a generic main-article text blob.
   - Return `{"data": {"title": <document.title>, "messages": [[role, text], ...]}}`.
   - Defensive: on 0 messages return `{"error": "...", "data": {...}}` — never crash.
2. **Platform service** `platform_v2/services/mailbox_scout_capture.py`:
   - `capture_share(url, owner_id=None, title=None) -> import_id`:
     `res = browser_service.run_skill_sync("chat_capture", {"url": url}, agent_id=..., timeout_s=120)`,
     map `res["data"]["messages"]` → `[(role, text, None), ...]`,
     `return mailbox_chat_service.ingest_chat(title or res["data"]["title"], msgs, owner_id)`.
   - `_ensure_import_paths()` first (KB #272154 — services lazily importing ai_bridge/dispatcher).
3. **Route** in `platform_v2/tools/mailbox_story/routes.py` (`@admin_required`):
   `POST /api/capture-share {url, title?}` → background thread → `capture_share(...)`.
   Add a "Capture share link" input+button in `mailbox_story.html` next to "Import chat export".
4. **DHQ-dispatchable capability** (so agents capture autonomously): register a capability
   (e.g. `chat_share_capture`) → map to S.C.O.U.T.'s department in `CAPABILITY_DEPARTMENT_MAP`
   (department_coordinator.py) AND seed an `agent_skills` row for S.C.O.U.T. The
   `delegate_task_worker` known-tool shortcut (delegation_service.py) can call
   `mailbox_scout_capture.capture_share` directly (deterministic, no LLM) — preferred over
   routing through an LLM agent.
5. **Tests** `platform_v2/tests/test_mailbox_scout_capture.py`: stub `run_skill_sync` to return
   a fake `{data:{messages:[...]}}`, assert `ingest_chat` called with mapped tuples; assert
   0-messages / error result raises/returns cleanly.

## Deploy/verify
- Rebuild scraper: `docker build -t archie_brain-archie_scraper -f archie-scraper/Dockerfile archie-scraper/`
  (or `docker compose up -d --build archie_scraper`). Restart `archie_platform` for the new
  platform service/route (volume-mounted).
- Verify with the owner's real ChatGPT share URL (the termination thread) — confirm the import
  lands and message count is plausible (NOT 15 — earlier under-capture lesson).
- Branch → test → F.O.R.G.E. review → merge via `gh pr merge --squash` on the live head →
  verify origin/main → queue C.O.D.E.X. docs (`delegate_task(capability='documentation')`).

## Still owed from this session
- **Queue C.O.D.E.X. docs for #1730** (post-merge step not done — context ran out).
- Earlier-deferred: per-import access grants (`mailbox_import_grants` table exists; branch
  `feat/mailbox-story-grants` is empty); entity-extraction prompt tuning.

## Sensitivity (carry forward)
Owner is assembling a federal-public-service termination/grievance record (emails + a ChatGPT
thread). Help = consolidation + WORDING only, NOT legal advice. Material is sensitive (medical
leave, mental health, named individuals). ALL enrichment of this content stays
`local_only=True` — never cloud.
