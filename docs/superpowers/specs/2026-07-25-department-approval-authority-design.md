# Department Approval Authority — design

**Date:** 2026-07-25
**Status:** design approved, not yet planned
**Owner decision:** Kytran
**Related:** #5194 (fail-closed merge gate, shipped in PR #2459), ADR-001/ADR-003 (tiered merge governance)

---

## Why

The platform runs 17 departments with AI directors, but **one agent reviews every change**.
`classify_pr_tier()` escalates purely by size and risk — Tier 3 above 1500 lines or on a
breaking/migration/security title, Tier 1 under 300 lines and 10 files when approved, Tier 2
otherwise — and its docstring names the actors: *"tier 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.),
3 (Kytran)."*

So today a 50-line change to `rbac.py` merges on F.O.R.G.E.'s approval alone. V.I.G.I.L. owns
Security & Compliance and never sees it. The organisation has department heads; the merge path
does not.

This design gives each director real approval authority in their own domain, escalating to
A.R.C.H.I.E. as COO and then to Kytran — the way a business delegates.

## Model

**Two orthogonal axes. They compose; neither replaces the other.**

| Axis | Question | Mechanism |
|---|---|---|
| **Risk** | How high must this escalate? | `classify_pr_tier()` — UNCHANGED |
| **Domain** | Whose area does this touch? | NEW: path → department ownership |

**Two keys are required to merge.** F.O.R.G.E. remains the code-review engine and judges the
change technically. The director owning each touched domain judges whether the change is right
*for their area*. Both must clear before the risk ladder applies.

This is deliberate: engineering reviews the code, the department head approves changes to their
department. A 50-line security change still needs V.I.G.I.L. even though it is Tier 1.

## Ownership routing

An explicit path → department map, CODEOWNERS-style. It extends machinery that already exists —
`_automerge_paths_allowed()` does path matching today for the sensitive-path gate — rather than
introducing a second matching engine.

Illustrative (the real table is set at implementation time with the owner):

| Path glob | Owning director | Department |
|---|---|---|
| `platform_v2/rbac.py`, `**/auth_*`, `**/security_network/**` | V.I.G.I.L. | Security & Compliance |
| `platform_v2/tools/department_hq/**`, `**/welfare_*` | K.I.N. | Human Resources & Culture |
| `platform_v2/tools/consciousness/**` | C.O.D.E.X. | Documentation & Knowledge |
| `ai_bridge/**`, `**/department_dispatcher.py` | F.O.R.G.E. | Engineering & Technology |
| `**/creed_*`, `standalone/kytran-creed/**` | E.T.H.O.S. | Legal & Regulatory |
| `database/migrations/**` | — | always Tier 3 (existing rule) |

A PR touching several domains requires sign-off from **each** owner it touches. Unmatched paths
default to F.O.R.G.E. as owner, so there is no unowned code.

**One source of truth.** The map is data, reviewable in a diff. It is NOT derived from
`module_registry` — modules do not map 1:1 to paths, and the highest-risk shared areas
(`platform_v2/services/`, `ai_bridge/`, `database/migrations/`) belong to no module at all.
Two sources that must be kept in step is the drift failure this codebase keeps hitting.

## Data model

New table, next free migration number (verify at implementation time; 462 is taken).

```
pr_domain_approvals
  id                serial PK
  pr_number         int      not null
  repo              text     not null
  department        text     not null   -- owning department
  required_agent_id int                 -- the director asked FIRST
  deciding_agent_id int                 -- who actually decided (may differ after escalation)
  status            text     not null   -- pending | approved | rejected | escalated
  escalated_to      int                 -- A.R.C.H.I.E. / Kytran when escalation occurred
  escalation_reason text                -- WHY, in words. Never null when status='escalated'
  matched_paths     jsonb    not null   -- the changed paths that triggered this ownership
  decided_at        timestamptz
  created_at        timestamptz default now()
  UNIQUE (pr_number, repo, department)
```

`required_agent_id` and `deciding_agent_id` are **separate on purpose**. The row must be able to
say "V.I.G.I.L. was asked, A.R.C.H.I.E. decided, because V.I.G.I.L. was at 131% of her 24h token
budget." Collapsing them into one column destroys exactly the fact an auditor needs.

**Surfaced through the existing unified approvals API.** `/api/approvals/pending` already unions
four sources (`autonomy_approval_queue`, `contractor_approval_requests`, `bridge_jobs`,
`hiring_candidates`). This joins in the same way, so pending domain sign-offs appear in the DHQ
Approvals tab, in front of A.R.C.H.I.E. and Kytran, with no new surface to build or maintain.

## Flow

1. F.O.R.G.E. completes its review → `mark_review_done()` (unchanged).
2. Resolve the PR's changed paths → set of owning departments.
3. Insert one `pending` row per owning department.
4. For each row, request the owning director's sign-off (see availability rules below).
5. The merge gate requires **every** row for that PR to be `approved`.

## Availability — welfare decides whether a director can be asked

Directors are agents. They rest, get benched, and hit token ceilings — 1,123 rest cycles in the
7 days to 2026-07-25, with several directors at 118–131% of their 24h token budget. "Wait for the
director" therefore has a real stall mode, and "always wake them" fights the welfare system.

| Director state | Action |
|---|---|
| `active` / `deployed` | Dispatch to them directly |
| `barracked` AND healthy — no open rest cycle, under token budget, not failure-benched, stress below `welfare:break:stress` | **Wake on demand** (`_wake_barracked_specialist()` already exists) and let them decide their own domain |
| Open rest cycle, over 24h token budget, failure-benched, or stress at/over the break threshold | **Do not disturb.** Escalate to A.R.C.H.I.E. |
| `winding_down` | **Do not wake.** Escalate. An agent ending their shift is not pulled back for routine sign-off. |
| Dispatch times out | Escalate |

**Absence is never consent.** A timeout, a benched director, or an unreachable dispatch escalates
the decision up the chain. It never auto-approves. This is the #5194 lesson restated: on
2026-07-25 PR #2458 merged on a `needs_changes` verdict because a path treated "a review
finished" as "a review approved."

**Every escalation records its reason in words.** Not `escalated=true` but
*"V.I.G.I.L. at 131% of 24h token budget — escalated to COO at 14:02."* Without this the system
quietly learns that escalating is cheaper than waking, department authority hollows out, and the
audit trail still looks clean. That is the exact failure shape this session kept finding: a status
that reads fine while the thing it describes is not happening.

**Chronic escalation is a staffing signal.** If a department's PRs routinely bypass its director
because she is over budget, that is the same overload condition
`recommend_pool_staffing_gaps()` already detects for dispatch. It must surface — not accumulate
silently. Ties to #5187 / #5188.

### Rejection is not absence

These are different states and must behave differently:

- **Absence** (timeout, resting, benched, over budget, `winding_down`) → **escalates**. Nobody
  decided, so the decision moves up the chain.
- **Rejection** (`status='rejected'`) → **hard block**. The owning director DID decide, and the
  answer was no. It does not escalate to A.R.C.H.I.E., because escalating a considered rejection
  is just shopping for a second opinion — it would make department authority decorative.

A rejection is cleared by the director changing their own decision, or by Kytran overriding it
explicitly as owner. Per `feedback_forge-no-silent-override`, an override must be written down,
not silently applied.

## Integration with the shipped merge gate

`github_service._automerge_governance_ok()` (PR #2459) already requires an approved F.O.R.G.E.
verdict AND tier within ceiling, fails closed on a missing row / unparseable verdict / any
exception, and is consulted before any GitHub call.

This adds **one more required condition**: every `pr_domain_approvals` row for the PR is
`approved`. Same fail-closed posture — a missing or pending row denies. `human_override=True`
continues to bypass for interactive authenticated callers only.

Gating at the choke point rather than per caller is deliberate and load-bearing: `merge_pr` has
five call sites, and per-caller gating is precisely how #5194 happened.

## Testing

Executed paths, not source assertions (KB #283579):

- Path map: a change under `rbac.py` resolves to V.I.G.I.L.; a multi-domain change produces one
  row per department; an unmatched path defaults to F.O.R.G.E.
- Gate: a PR with a `pending` domain row is refused; refused with **no GitHub API call**;
  approved only when every row is `approved`.
- Welfare: a healthy barracked director is woken; a resting / over-budget / benched /
  `winding_down` director is NOT woken and escalates instead.
- Absence: dispatch timeout escalates and does **not** auto-approve.
- Audit: an escalated row always carries a non-null `escalation_reason`, and
  `required_agent_id` != `deciding_agent_id` is preserved.

## Out of scope — deliberately

- **`classify_pr_tier()` is unchanged.** Risk and domain are orthogonal; two-key composes with the
  ladder rather than replacing it.
- **A.R.C.H.I.E.'s Tier-2 ceiling is NOT fixed here.** PR #2459 clamps her COO merge authority
  under `FORGE_AUTO_MERGE_MAX_TIER` — a F.O.R.G.E.-scoped setting applied to her path. That is a
  regression introduced while fixing #5194 and deserves its own fix, not bundling into a new
  feature. Filed separately.
- **Director review competence.** F.O.R.G.E. keeps the technical review; directors judge domain
  fitness. This design does not give every director a full code-review engine.
