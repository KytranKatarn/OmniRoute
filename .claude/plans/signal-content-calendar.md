# S.I.G.N.A.L. Content Calendar & Daily Generation — plan (owner vision 2026-06-10)

**Status**: spec — build in a FRESH session (deferred from cont-5: context budget + session length). Owner approved "plan it, ship the 2 launch posts now."

## Owner vision
1. **Backfill** the failed/staged LinkedIn posts into a calendar, **fanned 1-per-day across next week** (forward-scheduled — LinkedIn allows future dates, never past/backdating).
2. Once the backlog drains, **flip to daily fresh-content generation** to keep the cadence.
3. **PER-ACCOUNT** — separate calendars/backlogs/generation for each S.I.G.N.A.L. account: **Kytran (personal, browser profile 342)**, **Terry Caetano (personal real-name account, SEPARATE LinkedIn login → browser profile 343, added 2026-06-10)**, **KE Inc. (company)**, **Creed-AI (creed page)**. Kytran/KE/Creed all ride the 342 session (actor-switched); Terry is its own login + own one-time noVNC enrolment. The S.I.G.N.A.L. tab has the 4-account switcher — the calendar must scope to the selected account, not a shared queue.

## Hard constraints / gotchas
- **No backdating** — LinkedIn timestamps at publish. Re-posts are dated today; only forward-scheduling is possible.
- **Dedup by content FIRST** — there are ~40 `linkedin_post_log status='failed'` rows but many are dedup/retry artifacts from the broken-session window (Jun 8–10), NOT 40 unique posts. Use the content-keyed dedup from PR #1563 before scheduling, or you'll fan out 40 near-identical posts. Expect a much smaller unique set.
- **Approval-gated** — every scheduled post still releases to the existing linkedin_post approval queue → Telegram approve before it goes live. The scheduler promotes; the human still taps.
- **Session dependency** — posting now works via the persistent trusted profile (#3953, established 2026-06-10). Creed-page posts use agent 342's authenticated session (Kytran admins the Creed-AI page).

## Existing pieces to wire (don't rebuild)
- `social_posts.scheduled_at` + `agent_content_posts.scheduled_at` — scheduling columns already exist. Pick ONE as the calendar store (lean `agent_content_posts` — already account/agent-scoped).
- `creed_marketing_assets` (approved EN #5 / FR #6) — staged creed content.
- `linkedin_post_log` — post history (failed rows = the backlog source). NO scheduled_for column — it's a log, not a scheduler.
- Approval queue + agent_loop linkedin_post handler (content-keyed dedup, ?account filter) — PR #1563.
- S.I.G.N.A.L. Calendar sub-tab (`renderSignalCalendar` in department-hq.js) — UI surface for the per-account calendar.
- R.O.S.E.T.T.A. for FR (translate now routes correctly via #3977) + standing rule KB #272121 (non-EN via R.O.S.E.T.T.A.).

## 3-phase build
**Phase 1 — Backfill → schedule (per account):**
- Job/one-shot: gather failed `linkedin_post_log` + approved `creed_marketing_assets`, **dedup by content hash**, write unique posts into `agent_content_posts` with `scheduled_at` = next 7 days, 1/day, **tagged by account** (personal/company/creed).
- UI: show the scheduled queue per account on the Calendar sub-tab.

**Phase 2 — Daily release job:**
- APScheduler job (daily, `timezone="America/Toronto"`): find posts with `scheduled_at <= now` + not yet released, per account → promote to the linkedin_post approval queue → Telegram. Respects existing dedup + welfare/cost gates.

**Phase 3 — Daily generation (once backlog empty, per account):**
- When an account's scheduled backlog < N days ahead, dispatch `social_content` (→ S.I.G.N.A.L. director) to generate a fresh post grounded in that account's themes; FR via R.O.S.E.T.T.A. Auto-fills the calendar forward. Still approval-gated.
- Account themes: Kytran = personal/founder voice; KE Inc. = product/civic-intelligence; Creed-AI = ethics/governance (grounded in live C.R.E.E.D. evidence, like the marketing generator).

## Acceptance
- Each account has an independent 7-day calendar visible in the Calendar tab.
- 1 post/day releases to approval per account; nothing auto-publishes.
- Backlog dedup proven (unique count « 40).
- When backlog thins, generation tops it up without manual work.

## Refs
PR #1563 (Send to S.I.G.N.A.L. + content-keyed dedup), #3953 (persistent session — posting unblocked), #3977 (translate→R.O.S.E.T.T.A.), KB #272121 (non-EN via R.O.S.E.T.T.A.), creed_marketing_assets id5/id6.
