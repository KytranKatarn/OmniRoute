# A.R.C.H.I.E. COO Command Surface — Design

**Date:** 2026-07-12
**Extends:** `docs/superpowers/specs/2026-07-11-archie-coo-cockpit-design.md` (the shipped 4-slice cockpit: approvals, attachments, voice, face/presence)
**Status:** Design — pending Kytran's review
**Surface:** archie.kytranempowerment.com (the `archie_comms` cockpit)

---

## Vision — the Riker Doctrine

The cockpit is the **bridge**. Kytran is the Captain (Picard); A.R.C.H.I.E. is his Number One / COO (Riker).

Kytran commands **at altitude** — he talks to his Number One conversationally. She **runs the crew** (17 departments, ~50 agents): she consults them, coordinates the work, executes, and **relays their reports back in her own voice**. He never hails each crew member individually — he talks to Riker, and Riker runs the ship. The risky calls come back to the Captain for a yes/no; everything routine, she just handles.

One organizing principle, applied everywhere below: **one conversation → she commands the org → she reports in her voice with attribution → she gates state-changing actions back to the Captain.**

## Goals

From her cockpit chat, Kytran can:
- **Consult** any agent or department, and drop into module chats (V.I.G.I.L. security, R.E.S.O.L.V.E. mail, W.A.R.D.E.N. backups, …).
- **Act** — run tools/skills, take module actions, and approve things.
- **See** her comms hub (the DHQ **COMs** / Telegram feed) and **Mail HQ**, as panels where she works.

Interaction is **Hybrid**: natural language is primary ("what's V.I.G.I.L. seeing on security?", "have R.E.S.O.L.V.E. draft a reply and send it", "approve the family_tree fix"), with explicit affordances — a department/module switcher, the COMs + Mail panels, and quick-action buttons — for precision and discoverability.

## Non-goals

- **No new orchestrator service** — reuse the DHQ dispatcher for all agent work.
- **No agent speaking directly to Kytran** — unified voice; she relays with an ⟨agent⟩ attribution badge.
- **No bypass of the approval gate** for state-changing actions.
- **No direct Ollama** — all inference through DHQ (ADR-013); embeddings are the documented exception.

## Architecture

Keep the cockpit **thin** — its established pattern: UI + fail-soft proxies → platform internal endpoints behind `@_require_internal_key` (Bearer `INTERNAL_API_KEY`). Add one new piece: a **cockpit intent-router** that classifies each chat turn into one of three lanes.

```
Kytran (Captain)  ─talk/affordance─►  Cockpit intent-router
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        ▼ Lane 1: CONSULT                  ▼ Lane 2: ACT                      ▼ Lane 3: SURFACE
  platform /api/internal/coo/consult   capability/skill/approval action   COMs feed + Mail HQ
        │                                  │  (reads free;                    panels
        ▼                                  ▼   state-change → approval tier)   │
  DHQ dispatch → agent/dept          existing approval + skill surfaces   telegram_service /
        │                                  │   (#2207 approvals, Tier-1/2)     email_manager
        ▼                                  ▼                                   │
  reply relayed in HER voice          Telegram / in-cockpit approve       (she already polls
  + ⟨agent·model⟩ attribution          → execute                            Telegram messages)
```

### The intent-router (cockpit-side)
- Runs on her **fast cockpit model** (llama3.2:3b — now kept warm by the node keep-warm work) for cheap intent classification + slot extraction: `{lane, target_agent|department|module, action, args}`.
- The **explicit affordances are the deterministic fallback**: a switcher pick or a quick-action button bypasses NL parsing entirely (no misroute risk).
- **Ambiguous intent → she asks a clarifying question in-voice**, never guesses a state-changing action.
- Substantive answers keep the existing **`{{DEEPEN}}` two-tier** behavior (fast reply now, fuller 7B follow-up as a new message).

### Lane 1 — Consult (agent / department / module)
`POST /api/internal/coo/consult {target, prompt}` → `dispatch(capability|prefer_agent=..., prompt=..., local_only=True)` → she relays the answer in her voice + ⟨agent·model⟩ badge. **Module chats fold in here** — a module's overlay agent (V.I.G.I.L., R.E.S.O.L.V.E., …) is just a consult target. All welfare-, cost-, and C.R.E.E.D.-gated by virtue of going through DHQ.

### Lane 2 — Act (tools / skills / approvals)
Maps intent to a capability, a known skill, or an approval action. **Reads run free; anything state-changing** (send mail, run a mutating skill, change config, publish) **routes through the existing approval tier** — the same Telegram / in-cockpit approve already used for Tier-2 and the #2207 approvals surface. Sovereign fail-closed (local-only default; cloud stays gated).

### Lane 3 — Surface (panels)
The **COMs / Telegram feed** and **Mail HQ** render as cockpit panels alongside the chat (the Hybrid affordances). The cockpit already ingests Telegram messages via its 5-second poll, so COMs extends existing wiring rather than adding a new bridge.

## Slices (each ships on its own; this is the sequence)

### Slice 1 — Agent & Department Chat *(foundation)*
The intent-router + the Consult lane. Platform: `/api/internal/coo/consult`. Cockpit: NL routing + a department/agent switcher affordance + attribution badge (already exists from Slice 4). **Done when:** "ask V.I.G.I.L. about the firewall alert" returns V.I.G.I.L.'s real answer, relayed in her voice with attribution, welfare/cost-tracked in DHQ.

### Slice 2 — COMs / Telegram Hub
Migrate the DHQ COMs tab (Telegram message feed + config + A.R.C.H.I.E.'s unified voice) into the cockpit as a panel. **Default decision:** the cockpit becomes the **primary** home; DHQ keeps a thin read-only view (retire fully only if you'd rather). Reuses `telegram_service` + the existing message store/poll.

### Slice 3 — Mail HQ
Inbox / triage / reply panel over `email_manager` (R.E.S.O.L.V.E. drafts, the Smart-Inbox pipeline). Reads free; **send gated** through the existing approve-to-send path.

### Slice 4 — Tools & Actions
Broaden the Act lane: run a curated set of skills/tools + module actions + a wider approval set, all tier-gated with the same Telegram-style confirmation.

## Safety & governance

- **Unified voice** — she is the sole outbound voice; crew outputs are relayed with ⟨agent⟩ attribution (no agent DMs Kytran).
- **Approval** — state-changing actions → existing approval tier (Telegram / cockpit). Reads free. Sovereign fail-closed.
- **Auth** — every cockpit→platform call behind `@_require_internal_key`; the cockpit itself behind Kytran SSO.
- **Accounting** — all consults go through DHQ dispatch → welfare, cost, C.R.E.E.D., and `task_execution_log` visibility. No direct Ollama.

## Testing

- **Per slice:** platform internal-endpoint tests (routing, auth 401, dispatch mapping) + cockpit proxy/parse tests (intent classification, marker handling, fail-soft when a lane is degraded) + one live round-trip.
- **The router:** unit tests for classification (consult vs act vs surface), target extraction, and *ambiguous → clarify* (never auto-fire a state-changing action on a low-confidence parse).
- **Fail-soft everywhere:** a degraded lane never breaks the chat — she says she couldn't reach that crew member and offers an alternative.

## Open decisions (resolved in each slice's implementation plan)

1. **COMs:** migrate-and-retire the DHQ tab vs primary-in-cockpit-with-DHQ-mirror (**default: primary in cockpit, thin DHQ mirror**).
2. **Router split:** how much NL classification runs on the fast model vs deterministic affordance routing (**default: affordance is authoritative when used; NL for free-form**).
3. **Quick-action set** for Lane 2 (which actions get a button vs NL-only).

---

*Each slice becomes its own implementation plan (writing-plans) → build → F.O.R.G.E. review → deploy → verify. Slice 1 is the foundation the others build on.*
