# Compliance Auto-Remediation → Repair Bay Approval Flow

**Date:** 2026-04-11
**Status:** Design approved, ready for implementation plan
**Related:** PR #34 (interim kill-switch — to be removed by this work), 2026-04-11 ip_forward incident, PR #32 (AI Remediation Planning shipped the Repair Bay plumbing for blocklisted rules)

---

## 1. Problem

Compliance Job #58 `run_auto_remediation` ran every 6h and silently applied any failing rule tagged `fix.risk=low` by calling `apply_fix(…, user_id=0)` directly. On 2026-04-11 it wrote `net.ipv4.ip_forward=0` via `/etc/sysctl.d/99-compliance.conf`, killing all Docker container forwarding for hours. Root cause: the tier-1 auto-apply path had **no post-apply health check, no rollback, no admin alert**, and several rule-pack entries had unsafe `fix.risk=low` tags for actions that affect Docker-critical infrastructure.

PR #32 shipped the plumbing to route **blocklisted** rules through Repair Bay so F.O.R.G.E. generates a plan the admin reviews. But non-blocklisted low-risk rules bypassed that flow entirely. The interim fix (PR #34) gated Job #58 off behind an env var; that's a kill-switch, not an architecture.

## 2. End-State

Every failing compliance rule becomes a card in Repair Bay. The admin approves from there. Nothing is ever applied without either (a) a direct human click or (b) a Sunday maintenance-window auto-apply pass that only runs rules the human has previously opted in on, with health check + rollback on every execution. The platform is safe-by-construction.

## 3. Design Decisions (from brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Autonomy model | **C** — Opt-in per rule + maintenance window gate (SaaS-product pattern we'd also sell) |
| 2 | Repair Bay card buttons | **C** — Three buttons: `Apply once` / `Apply + always allow` / `Dismiss (mark exempt)` |
| 3 | Health check scope | **B** — dashboard HTTP + container count + container→external + P.R.O.B.E. smoke suite |
| 4 | Rollback coverage | **C** — Only `sysctl` / `file_line` / `service` fix types eligible for auto-apply; `command` types require manual click every time |
| 5 | Maintenance window | **A** — Hardcoded `Sunday 03:00–04:00 America/Toronto`, max 5 fixes per window |
| 6 | Telegram alerts | **B** — Digest per window + immediate alert if rollback itself fails |

## 4. Architecture

### 4.1 Data model (1 new table)

```sql
CREATE TABLE IF NOT EXISTS compliance_rule_auto_approvals (
    rule_id           VARCHAR(100) PRIMARY KEY,
    pack_id           VARCHAR(100) NOT NULL,
    status            VARCHAR(20) NOT NULL
                      CHECK (status IN ('allow','exempt')),
    approved_by       INTEGER REFERENCES users(id),
    approved_at       TIMESTAMP DEFAULT now(),
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS idx_comp_auto_approvals_status
    ON compliance_rule_auto_approvals(status);
```

**Semantics:**
- `status='allow'` — rule qualifies for Sunday auto-apply **if** `fix_type ∈ (sysctl, file_line, service)`. Command-type fixes ignore `allow` and still require manual click.
- `status='exempt'` — rule never generates Repair Bay cards and is excluded from compliance score denominator.
- Reuses `improvement_proposals` table (no schema changes) for the cards themselves. `category='compliance_fix'` already exists.

### 4.2 Flow

```
Job #57 scan (every 6h)
  → writes compliance_scan_results
  → 30m later: Job #58 run_compliance_enqueue
      for each FAIL in latest scan:
        skip if exempt
        skip if open card already exists for rule_id
        skip if blocklisted (Job #61 handles those via F.O.R.G.E. plan)
        INSERT improvement_proposal
          (category='compliance_fix', status='pending_approval',
           metadata={scan_id, rule_id, fix_def, fix_type, risk_level,
                     auto_apply_queued: (allow AND fix_type eligible)})

Two execution entry points, both end at _safe_execute_fix:

  A. Admin click in Repair Bay
       POST /api/proposals/<id>/compliance-action {action}
         action=apply_once     → _safe_execute_fix
         action=apply_and_allow → set status='allow' + _safe_execute_fix
         action=exempt          → set status='exempt' + mark card resolved

  B. Sunday 03:00 EDT — Job #62 run_auto_apply_window
       CronTrigger(day_of_week='sun', hour=3, minute=0, tz='America/Toronto')
       Fires ONCE at 03:00, runs to completion.
       Typical runtime: 5 fixes × ~15s health gate = <2 minutes.
       The "window" is a conceptual safety slot (03:00–04:00 EDT) —
       the cron is a single firing, capped at 5 fixes, with hard
       timeout of 15 minutes after which remaining cards defer to
       next week.
       pick up to 5 cards where metadata.auto_apply_queued=true
       for each:
         re-verify fix_type still in (sysctl, file_line, service)
         _safe_execute_fix(proposal_id, user_id=0)
       send Telegram digest at end
```

### 4.3 `_safe_execute_fix(proposal_id, user_id)`

Single safety gate for **both** entry points. Steps:

1. **Load proposal** — fetch `fix_def`, `rule_id`, `fix_type`.
2. **Snapshot pre-state**, dispatched by fix_type:
   - `sysctl` → read current `sysctl -n <param>` value
   - `file_line` → read file contents + SHA256 hash
   - `service` → read `systemctl is-enabled <svc>` + `is-active <svc>`
3. **Apply fix** via existing `compliance_service.apply_fix_approved(scan_id, rule_id, user_id)` (currently dead code — this wiring activates it).
4. **Wait 10 seconds.**
5. **Health gate** — all four must pass:
   1. `curl -f http://localhost:3000/health` returns 2xx
   2. `docker ps -q | wc -l` == baseline captured before step 3
   3. `docker exec archie_platform curl -f -m 5 https://www.google.com` returns 2xx
   4. `run_qa_suite('compliance-smoke')` returns `status='passed'`
6. **On green:** mark proposal `status='resolved'`, log success.
7. **On red:** call `_rollback(snapshot)`:
   - `sysctl` → `sysctl -w <param>=<old_value>` + `rm /etc/sysctl.d/99-compliance.conf`
   - `file_line` → write original contents back if hash changed + restart service if `restart_service` was in fix_def
   - `service` → restore `enabled`/`active` state via `systemctl`
   Re-run the health gate.
     - Rollback green → mark proposal `status='rolled_back'`, log.
     - Rollback red → mark proposal `status='rollback_failed'`, **fire immediate Telegram alert** with snapshot details, raise exception.

### 4.4 P.R.O.B.E. smoke suite

New file `platform_v2/qa_suites/compliance-smoke.yaml`:

```yaml
name: compliance-smoke
description: 15s health canary for compliance auto-apply safety gate
steps:
  - get: /health                    # dashboard binding
  - get: /tools/security-network    # admin auth + module
  - get: /tools/repair-bay          # approval UI
  - get: /tools/dashboard           # renderer
```

Invoked by `_safe_execute_fix` via the existing `run_qa_suite()` service (**not** direct Playwright — per `feedback_probe-over-playwright.md`).

## 5. File-Level Changes

| # | File | Action | ~LOC |
|---|---|---|---|
| 1 | `database/migrations/316_compliance_rule_auto_approvals.sql` | **new** | 15 |
| 2 | `platform_v2/tools/security_network/compliance_safe_exec.py` | **new** | 180 |
| 3 | `platform_v2/qa_suites/compliance-smoke.yaml` | **new** | 10 |
| 4 | `platform_v2/tools/security_network/jobs.py` | modify — rename Job #58, add Job #62, remove env kill-switch | ~50 net |
| 5 | `platform_v2/tools/security_network/compliance_service.py` | modify — add `set_rule_auto_approval`, `get_rule_auto_approval`, `_is_rule_exempt`, wire `apply_fix_approved` | ~60 |
| 6 | `platform_v2/tools/repair_bay/proposal_routes.py` | modify — branch `proposals_execute` on `compliance_fix`, add `/compliance-action` endpoint | ~40 |
| 7 | `platform_v2/static/js/security-network-app.js` | modify — add 3 buttons to compliance card modal | ~30 |

**Total:** ~385 net LOC across 7 files.

## 6. Cleanup In Same PR

- Remove `COMPLIANCE_AUTO_REMEDIATION_ENABLED` env gate (replaced by architecture).
- **Keep** blocklist entries for `D-238007` / `D-238008` as defense-in-depth — they're command-type so the new architecture blocks auto-apply anyway, but the blocklist entry ensures Job #61 generates a F.O.R.G.E. plan which is a nicer UX than a bare card.

## 7. Testing

1. **Migration dry-run** — apply `316_*.sql` on a DB snapshot, verify idempotency (run twice).
2. **Green-path sysctl fix** — pick `CIS-3.1.2` (`net.ipv4.conf.all.send_redirects=0`). Enqueue card → click `Apply once` → verify sysctl changed, health gate green, proposal resolved.
3. **Rollback path** — add a temporary feature flag `FORCE_HEALTH_GATE_FAIL=1`. Re-run the same fix. Verify: fix applied → health gate fails → rollback restores `send_redirects` to prior value → proposal marked `rolled_back`.
4. **Rollback-failed path** — feature flag both health gate AND rollback to fail. Verify: immediate Telegram alert fires, proposal marked `rollback_failed`, platform still running (nothing else touched).
5. **Auto-apply window** — click `Apply + always allow` on a sysctl fix → DELETE the card from DB to simulate "new scan same failure" → run `run_auto_apply_window` manually outside the window (should no-op) → time-travel the window clock → verify card picked up, applied, digest sent.
6. **Cap enforcement** — enqueue 10 auto_apply_queued cards, run window job, verify exactly 5 processed and the remaining 5 left for next week.
7. **Command-type guard** — approve a `command`-type rule with `Apply + always allow`. Verify the allow flag is written BUT the window job skips it because `fix_type` is ineligible.
8. **P.R.O.B.E. smoke suite** — run `run_qa_suite('compliance-smoke')` manually, verify all four checks pass in <20s.

## 8. Out of Scope (future)

- Configurable maintenance windows (table-driven). v1 is hardcoded.
- Per-rule `auto_apply_allowed_by_tenant` for multi-tenant standalones. Platform-level only for v1.
- Generic `command`-type rollback via tar snapshot. Deferred until a specific command rule needs it.
- Alerting to Slack / email / PagerDuty. Telegram only for v1.

## 9. Acceptance Criteria

- [ ] A failing non-blocklisted rule never applies without either a direct admin click or a prior `Apply + always allow` approval
- [ ] `_safe_execute_fix` is the only code path that mutates system state for compliance fixes
- [ ] Every fix execution is preceded by a snapshot and followed by the 4-check health gate
- [ ] Failed health gate triggers rollback; failed rollback triggers immediate Telegram alert
- [ ] Window job is capped at 5 fixes and only runs inside the Sunday 03:00–04:00 EDT slot
- [ ] `COMPLIANCE_AUTO_REMEDIATION_ENABLED` env var is no longer referenced anywhere
- [ ] `apply_fix_approved` is called from `_safe_execute_fix` and nowhere else
- [ ] P.R.O.B.E. `compliance-smoke` suite exists and passes against a healthy platform
