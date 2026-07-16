# Collaborator Persona Email Assistant — Design (Slice 1: Foundation + Email)

**Date:** 2026-07-16
**Owner:** Kytran
**Project:** Collaborator Persona-Assistants (new; follow-on to #388 Agent Directory Integrity)
**Status:** Approved (design decisions); spec pending owner review
**Scope:** Slice 1 of 4. The **21 `human_agent` collaborator agents** only.

---

## Problem

The platform has **21 human collaborators** — `agents` rows with `worker_type='internal'`,
`status='active'`, and a `human_agent` mailbox (the COLLABORATOR marker). They already have
complete bios, personalities, portraits, and system prompts. But there is no working
"assistant" layer for them: email AI today is a single agent (**R.E.S.O.L.V.E.**) drafting on
**owner/business** mailboxes only. The owner wants each collaborator to run a *simple LLM* that
helps manage **their** company email — voiced as that person — and later their work + social
posting.

## Goal

Give each of the 21 collaborators a right-sized simple LLM and a **persona-voiced email-drafting
assistant**: for `action`-priority inbound to their mailbox, draft a reply *in their voice* →
**owner approves** via Telegram/Approvals → **auto-send**. Reuse the existing Email Manager
draft→approve→send pipeline as much as possible.

## Key decisions (owner-approved)

- **Scope:** Slice 1 = **Foundation + Email assist**. Work/jobs assistant and social posting
  (Media Hub + S.I.G.N.A.L.) are later slices.
- **Model:** **ONE shared small model — `llama3.2:3b`** (already a hub warm model) — assigned to
  all 21 collaborators. Persona/voice comes from each agent's existing bio + system_prompt, not
  the model.
- **Autonomy:** **Draft → OWNER approves (Telegram [Send/Cancel] / DHQ Approvals) → auto-send.**
  Single approver (the owner) for all 21. Reuses the existing owner approve-to-send pipeline.

## The 21 collaborators (identified by `human_agent` mailbox)

`agents.id`: 9 Nexus · 11 Scholar · 22 Helix · 33 Sage · 41 Tempo · 43 Oracle · 54 Medic ·
55 Envoy · 92 Oksana · 107 Crucible · 341 Amina · 343 Lucia · 346 Maya · 347 Lillian ·
348 Josée · 355 Grace · 356 Régine · 357 Adrienne · 358 Soleil · 359 Marco · 360 Emmanuel.

All have full bios + portraits + personality + `system_prompt`. 4 have `model=none` (Lucia,
Maya, Lillian, Josée); several are on oversized/wrong models (e.g. `phi4:14b`, `gemma3:12b`,
`arctic-embed-cpu` which cannot chat) — all normalized to `llama3.2:3b` by the Foundation step.

**Not in this set (deliberately):** Kytran #342 + Terry Caetano #377 (Executive-Office *owner*
identities, no `human_agent` mailbox); CodeSmith #4 (internal AI worker, no collaborator
mailbox). Terry #377's bare profile (fillable from his LinkedIn / Kytran's bio) is a separate,
owner-gated task, not part of this slice.

---

## Design

### Component 1 — Foundation: shared simple model

- Set `model='llama3.2:3b'` for all 21 collaborators via
  `agent_service.update_agent(agent_id, model='llama3.2:3b')` — **single-writer, no raw SQL** on
  the `agents` table.
- `llama3.2:3b` is already in the hub warm set (`.claude/rules/ai-bridge.md`) — no new cold-load
  infrastructure, one warm model serves all 21.
- **Idempotent** — re-running is a no-op for agents already on the model.
- Trade-off (owner-accepted): any *non-email* capability dispatch routed to these agents now uses
  the small model too — consistent with "a very simple LLM."

### Component 2 — Per-collaborator persona drafting

- **Extend the email-draft path** — today the `mailhq_draft_proposals` job (10-min, in Email
  Manager) drafts via R.E.S.O.L.V.E. (`capability='support'`) on **owner/business** mailboxes
  only (`draft_proposal_service`). Extend it to **also cover `mailbox_type='human_agent'`
  mailboxes**, routing each to its own collaborator persona.
- For each `email_messages` row in a collaborator mailbox with `ai_priority='action'` and no
  existing draft:
  1. Resolve the mailbox's collaborator agent via `email_mailboxes.owner_agent_id`.
  2. Build the drafting prompt = the inbound email/thread + "draft a reply in <name>'s voice."
  3. Dispatch via **`services.cluster_dispatch.queued_dispatch_text(...)`** with
     `system_prompt=<collaborator's system_prompt>`, `model_override='llama3.2:3b'`,
     `local_only=True` — **cold-load-tolerant** (polls `dispatch_pending_queue` through a cold
     load; NEVER `dispatch_json`, which masks cold-load queueing — KB mistake #276153).
  4. Persist the result to `autonomy_approval_queue` with `action_type='email_reply'` (the exact
     shape the existing approve-to-send pipeline consumes), tagged with the mailbox +
     collaborator name so the Telegram/Approvals card shows *whose* reply it is.
- **Persona voicing:** the collaborator's `system_prompt` (which encodes their bio/role/voice)
  IS the drafting system prompt — the draft reflects that person.

### Component 3 — Approval → send (REUSED; extend coverage only)

- Draft in `autonomy_approval_queue` → owner Telegram **[Send/Cancel]** (single-token callbacks
  `email_replysend_<id>` / `email_replycancel_<id>`) → **`execute_email_reply`** (idempotent,
  shared by the Telegram tap AND DHQ Approvals) → `send_service.send_email_via_stalwart`.
- **No change** to the approval/send mechanics — the only difference is that the queue now
  contains collaborator-mailbox drafts. The card must display which collaborator/mailbox the
  reply is for (so the owner has context approving 21 people's mail).

### Data flow

```
inbound email
  → collaborator human_agent mailbox
  → IMAP sync (5-min)
  → AI triage sets email_messages.ai_priority
  → draft job (welfare-gated) picks ai_priority='action' items
  → persona draft: queued_dispatch_text(system_prompt=<collaborator>, model_override=llama3.2:3b)
  → autonomy_approval_queue (action_type='email_reply', tagged w/ collaborator)
  → owner Telegram [Send/Cancel]  (or DHQ Approvals)
  → execute_email_reply
  → Stalwart SMTP send
```

### Error handling

- **Cold-load tolerance:** always `queued_dispatch_text` — never the synchronous `dispatch_json`
  (KB #276153). A cold model queues + drains rather than failing.
- **Welfare gating:** inherit the existing `mailhq_draft_proposals` welfare gate.
- **Reply-loop safety:** the existing self-send / no-reply-loop guards apply unchanged.
- **Independent toggle:** add `platform_settings mailhq:draft:collaborators` (bool, default
  **off** until verified) so collaborator drafting can be enabled/disabled without touching the
  owner/business draft path.
- A collaborator with no `action` mail → no drafts (idle is fine).

### Settings / controls

- `mailhq:draft:collaborators` (bool, default off) — gates the new collaborator drafting.
- Reuse existing `mailhq:*` draft tunables (cadence, quiet hours).

### Testing (TDD)

- **Foundation:** `update_agent(model='llama3.2:3b')` sets the model for each of the 21;
  idempotent; goes through the single-writer (no raw SQL).
- **Drafting:** given an `action` inbound to a collaborator mailbox, a draft is produced using
  **that collaborator's** `system_prompt` (persona reflected in output) + `llama3.2:3b`, and
  lands in `autonomy_approval_queue` as `action_type='email_reply'` tagged with the collaborator.
- **Cold-load:** drafting calls `queued_dispatch_text` (assert, not `dispatch_json`).
- **Approval→send:** an approved collaborator draft calls `execute_email_reply` → send (mock
  SMTP); idempotent (double-tap doesn't double-send).
- **Negative:** `info`/`review`-priority mail → no draft; drafting off when
  `mailhq:draft:collaborators` is false.

---

## Out of scope (later slices)

- **Work/jobs assistant** — help each collaborator run their tasks here (daily "what needs you").
- **Social posting** — life/work images via **Media Hub + S.I.G.N.A.L.** **REQUIREMENT for that
  slice (owner, 2026-07-16):** image gen must produce recognizably-consistent images of each human
  collaborator — the **same face + body** across different **outfits + environments**. Use Media
  Studio's **IP-Adapter face-consistency path** (`portrait_service.generate_variant` + each
  collaborator's `agent_portraits.ip_adapter_ref_path`, anchored to their canonical portrait) plus
  an accurate person-description prompt (build / features / skin-tone) so the person stays
  identifiable. **Foundation prep for this:** confirm each of the 21 has a canonical portrait (they
  do, from #4949) **and** an approved `ip_adapter_ref_path` (may need generating per collaborator —
  `generate_variant` requires an approved canonical with `ip_adapter_ref_path`).
- **Per-collaborator self-approval** — the owner is the sole approver in Slice 1.
- **Right-sizing / assistants for the non-collaborator internal AI agents** (CodeSmith, etc.).
- **Terry #377 profile fill** — separate owner-gated task.

## Risks / open questions

- **Owner approval volume:** if many collaborators receive `action` mail, the owner's approval
  queue could grow. Watch daily volume; a per-collaborator digest or batching is a later
  enhancement (not MVP).
- **Persona quality on a 3B model:** `llama3.2:3b` drafting in-voice may be uneven. Acceptable for
  MVP because the owner approves every send. If quality is poor, bump the shared model one tier.
- **Model downgrade side-effect:** these agents also carry non-email skills; normalizing to
  `llama3.2:3b` affects any capability work routed to them (accepted per "one shared simple
  model").
- **Draft dispatch routing/attribution (plan must confirm):** the existing draft path routes
  `capability='support'` → R.E.S.O.L.V.E. For collaborator drafts we force the persona via
  `system_prompt=<collaborator>` + `model_override='llama3.2:3b'`, so the *capability* only picks a
  node/queue. The plan must confirm (a) which capability to route under, and (b) that the draft is
  attributed to the collaborator (not R.E.S.O.L.V.E.) in the approval card + logs — passing the
  collaborator's `system_prompt` + `model_override` should yield in-voice output regardless of the
  routed agent, but attribution needs a verify.

## Non-goals

- No cloud inference, no direct Ollama, no raw SQL on `agents`.
- No auto-send without owner approval.
- No new approval UI — reuse Telegram [Send/Cancel] + DHQ Approvals.

---

## Implementation notes (for the plan)

Key existing surfaces the implementer must read first:

- `platform_v2/tools/email_manager/draft_proposal_service.py` — current draft logic (imports
  `queued_dispatch_text`; drafts via `capability='support'`).
- The `mailhq_draft_proposals` job (Email Manager) — 10-min draft producer to extend.
- `autonomy_approval_queue` + `execute_email_reply` + the `email_replysend_`/`email_replycancel_`
  Telegram callbacks — the approve-to-send pipeline (unchanged, extend coverage).
- `email_mailboxes` (`owner_agent_id`, `mailbox_type='human_agent'`, `department`) + the triage
  that sets `email_messages.ai_priority`.
- `services/agent_service.py::update_agent` — single-writer for the Foundation step.
- `services/cluster_dispatch.py::queued_dispatch_text` — cold-load-tolerant dispatch.

All LLM inference `local_only` (ADR-013); all `agents`-table writes via `agent_service`
(single-writer); email drafting welfare-gated + owner-approved (never auto-send).
