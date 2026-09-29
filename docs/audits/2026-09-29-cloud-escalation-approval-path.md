# Cloud throughput escalation — how the approval path actually behaves

**Date:** 2026-09-29 · **Author:** opencode lane (Applications & Concepts)
**Scope:** read-only investigation. No configuration was changed.
**Subject:** `autonomy_config.archie_coo_approve`, the COO approval worker
(`ai_bridge/agent_loop.py::_archie_coo_approval_worker`), and the
`autonomy_approval_queue` rows for `action_type='cloud_throughput_escalation'`.

## Why this was looked at

The owner asked whether the recurring "cloud" Telegram messages were approval
requests at all, or something being auto-approved. They are **not** approval
requests, and the investigation changed its own conclusion twice. Both corrections
are recorded below, because the wrong version of this finding is the more
alarming one and it would be easy to repeat.

## What actually happens

`autonomy_config` → `archie_coo_approve`:

```json
{"types": ["cloud_throughput_escalation", "contractor_dispatch"],
 "contractor_cost_ceiling_usd": 2.0}
```

`ai_bridge/agent_loop.py:5409` `_archie_coo_approval_worker()` selects up to 5
pending tier-2 rows of those types on a 60s tick, flips them to `approved`, and
sends Kytran a Telegram notice. Its own docstring is explicit that the message is
**"informational — not a prompt"**. So the owner is not being asked to approve
anything; escalation is a standing, pre-delegated authority.

Every dispatcher call site raises the request with `tier=2` (wait for a human);
the worker is what converts that to `approved` under the delegated authority.

### Volumes (2026-09-28/29, measured)

| Measure | Value |
|---|---|
| `cloud_throughput_escalation` rows, all time | 4,896 |
| … in the last 24 h | 258 |
| … in the last hour | ~24 (≈1 per 2.5 min) |
| Status distribution, all time | executed 19,605 · expired 524 · cancelled 484 · failed 375 · **rejected 110** · denied 2 |
| Target model | `qwen3-coder-next:cloud` (Ollama Cloud) |
| Result of those cloud calls | `success: false` on every recent one |

## Finding 1 — the queue column is misleading; the trail is fine

**First conclusion (WRONG):** 4,615 executed rows have `approved_by IS NULL`,
which reads as 96% of paid-cloud spend authorised by nobody.

**What is actually true:** the COO worker records its attribution in
`execution_result` (`approved_by_role: coo`, `approved_by_agent: A.R.C.H.I.E.`,
`auto_approval: true`) and never writes the `approved_by` column. The executor
then **overwrites** `execution_result` with the run result, destroying the
signature. A search of `execution_result` finds **0 of 4,896** rows carrying it —
which is what made the first conclusion look airtight.

But the worker also calls `log_governance_event(...)`, and that write survives:

- `governance_audit_log`, `action = 'coo_approve:cloud_throughput_escalation'`
- **4,576 of 4,615** NULL-`approved_by` executed rows (99.2%) join back to a
  governance entry carrying `{"approved_by": "A.R.C.H.I.E."}`
- 4,579 such entries all time; 253 in 24 h

**So the audit trail is intact and attributable.** The defect is narrower and
duller than it first looked: the convenience column on the queue is not populated,
so anyone reading the queue — including the Repair Bay approvals UI — sees
unattributed spend and has to know to join to another table to learn otherwise.

The 39 unmatched rows (0.8%) are worth a look, but they are not evidence of
unauthorised spend.

## Finding 2 — the cost ceiling does not cover cloud escalation

`archie_coo_approve` carries `contractor_cost_ceiling_usd: 2.0`, and the worker
**enforces it — for `contractor_dispatch` only**:

```python
if item["action_type"] == "contractor_dispatch":
    est_cost = float(adata.get("estimated_cost_usd") or 0)
    if est_cost > cost_ceiling:
        continue          # skip, do not approve
```

`cloud_throughput_escalation` has **no equivalent check**. A per-event dollar
guard exists for one paid action type and not for the other, and the cloud path
can therefore be auto-approved without bound. Whether that asymmetry is intended
is an owner decision; it is not documented anywhere I could find.

## Finding 3 — the escalation is not achieving anything

Every recent escalation returns `{"model": "qwen3-coder-next:cloud",
"success": false, "executed": true}`. Roughly 260 notifications and auto-approvals
per day are being generated for calls that fail. The triggering work is small,
high-frequency batch jobs (`capability: factcheck_quick` on `wtf_hub_quick` —
"extract up to 3 factual claims", "classify political bias") saturating the local
mesh, so the local fleet is at capacity and falls through to paid cloud.

This is the substantive problem: the escalation is not a safety valve absorbing
spare capacity, it is a **symptom of local contention** being paid for without
result. Fixing the contention would remove the cause; the approval path is only
the messenger.

## Recommendations (owner-side; none applied)

1. **Populate `approved_by`** when the COO worker approves, so the queue is
   self-describing and the join is not required to answer "who authorised this".
   Smallest change with the clearest benefit.
2. **Decide whether cloud escalation should carry a cost ceiling** like
   contractor dispatch does, and record the decision where the config is.
3. **Address the `factcheck_quick` contention** on the local fleet. This is the
   only change that stops the 260/day, rather than documenting them.
4. **Consider suppressing the Telegram** for a recurring informational event. The
   design intent (informational, not a prompt) is sound; ~1 message every 2.5
   minutes indefinitely trains the owner to ignore the channel, which would also
   hide the messages that do matter.

## Why the opencode lane did not fix any of this

`autonomy_config` and the COO approval worker govern **who may authorise paid
spend**. The guard-free lane has no scope guard and could edit them, but an agent
rewriting the rules that govern its own authority — on a finding about
auto-approval — is a conflict of interest, not a task. Investigation and
reporting only; the decisions stay with the owner.
