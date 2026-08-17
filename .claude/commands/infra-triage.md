# /infra-triage — diagnose an infrastructure alert to ROOT CAUSE before a human reads a log

**Task #5615.** One command that gathers the evidence an alert never quotes and returns a
verdict a human can act on. **READ-ONLY — never fix, never restart, never delete.** The
output is a diagnosis; acting on it is a separate, deliberate step.

## Input

`/infra-triage <alert title or source>` — or with no argument, triage the newest
unresolved system alerts:

```sql
SELECT id, title, severity, source, created_at FROM director_reports
WHERE category='system' AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY id DESC LIMIT 10;
```

(`system_notifications` is the older surface; check it too if director_reports is quiet.)

## Output contract (one block per alert — always ALL fields)

```
ALERT:        <title>
VERDICT:      real | false_positive | unknown
ROOT CAUSE:   <one sentence naming the mechanism, not the symptom>
EVIDENCE:     <the actual log/DB lines that prove it — quoted, with source path>
SUGGESTED FIX:<one concrete action>  MUTATING: yes|no
```

`unknown` is an honest verdict — never guess a root cause without naming the observation
behind it (feedback_absence-of-completion-is-not-failure). An empty query result is not
evidence of anything (KB #285009): always `2>&1`, always check the query itself ran.

## Step 1 — delegate the first pass to B.A.S.E. (free, parallel)

```python
mcp__archie__delegate_task(
    capability="infrastructure",
    reason="Triage alert to root cause (read-only): <title>. Quote the failing log lines.",
    delegation_source="claude",
)
```

Don't block on it — run the evidence ladder yourself in parallel and reconcile at the end.
B.A.S.E.'s answer is corroboration, never a substitute for the quoted evidence.

## Step 2 — the evidence ladder, by alert class

**General rule: the root cause is sitting in a log the alert never quoted. Find that log.**

### Backup / tier-freshness alerts (`backup_posture_monitor`, "stale", tier names)
1. `backup_log` — last rows for the named tier/component, **status column included**
   (`success` vs `failed`/`partial` — recency alone certifies nothing, #5013):
   `SELECT backup_type, component, tier, status, LEFT(notes,120), created_at FROM backup_log WHERE tier='<tier>' ORDER BY id DESC LIMIT 10;`
2. `/var/log/archie_backup.log` (host) — grep the component name ± 20 lines.
3. For gdrive: look for `invalid_grant` / `storageQuotaExceeded` — **OAuth death and quota
   look identical from the freshness alarm** (2026-08-15: assumed quota, was invalid_grant).
4. For vps/off-site tiers: `ssh <node> df -h` — **a 100%-full target is the per-component
   failure signature** (big dumps fail, small gitbundles still land; outpost-us 2026-08-02).

### Job / worker "wedged" alerts (approval executor, drain worker, `*_monitor` stalls)
1. Is it actually dead, or is one long task holding `max_instances=1`?
   `SELECT job_name, MAX(created_at) FROM autonomy_loop_log WHERE job_name='<job>' GROUP BY 1;`
   plus scheduler log: `docker logs archie_scheduler --since 30m 2>&1 | grep -E "<job>|maximum number of running instances"`.
   A 16-min `website_deploy` holding the executor produced a false "wedged" (2026-08-15).
2. `check_drain_liveness()` for dispatch-drain claims (requires `checked=True`, silence
   proves nothing).
3. A monitor "not firing" claim: check its OWN stamp is advancing before believing the
   alert about it (`dispatch_posture_monitor` was firing fine — false positive).

### Disk / SMART alerts (`SMART CRITICAL/WARNING: /dev/…`)
1. `sudo -n smartctl -a -j /dev/<X>` — attrs 5/197/198/199. Severity is the MODE:
   pending>0 with realloc==0 = failing (not remapping); realloc-only = aging as designed;
   199 = CABLE, different remedy. (scripts/smart_posture_monitor.py encodes this.)
2. `df -h` on the mount — a full disk produces cascade alerts blaming innocent components.

### Container / service-down alerts
1. `docker inspect <name> --format '{{.State.Status}} {{.RestartCount}} {{json .NetworkSettings.Networks}}'`
   — **Networks: {} while "running" is the KB #285320 trap**; and `exited` can be the
   CORRECT resting state (ComfyUI parks itself — check before "fixing").
2. `docker logs <name> --since 30m 2>&1 | tail -40` — the crash reason, not the health check.
3. Under `userland-proxy:false`, test reachability from ANOTHER container/machine, never
   host→own-published-port.

### Mail alerts (sync failures, auth errors)
1. Judge mailbox auth ONLY by the scheduler's sync line (per-IP throttle poisons ad-hoc
   imaplib tests). 155/156-style mass failure = the Stalwart ban signature: check
   `logs/stalwart.log.<date>` INSIDE the container for `security.ip-blocked` (stdout is
   empty; TCP-connect-OK-then-EOF on every port = ban, not TLS). Runbook: KB #290280.
2. Single-mailbox auth failure: check `audit_log` for `STALWART_SECRET_ROTATION` rows
   (#5698 made rotations self-attributing).

### Fleet / node alerts (offline, timeouts)
1. `SELECT node_name, last_heartbeat FROM remote_nodes ORDER BY last_heartbeat DESC;`
2. Node-attributed failures: `SELECT agent_name, capability, duration_ms, LEFT(error_message,80) FROM task_execution_log WHERE node_used_id=<id> AND NOT success ORDER BY id DESC LIMIT 10;` (#5700 made these visible).
3. A 7B timing out on a CPU-only or contended node is BACKPRESSURE BY DESIGN (#5623/#5407)
   — verdict false_positive w.r.t. "node broken", real w.r.t. capacity.

## Step 3 — reconcile and report

Merge your ladder evidence with B.A.S.E.'s answer. Where they disagree, the QUOTED LOG
wins. Emit the output contract per alert. If any verdict is `real` with a mutating fix,
END with the fix as a recommendation — do not apply it (read-only contract).

## Calibration — the four 2026-08-15 alerts this command must reproduce

| Alert | Verdict | Root cause (found in the un-quoted log) |
|---|---|---|
| approval executor "wedged" | false_positive | a 16-min `website_deploy` held `max_instances=1` |
| dispatch_posture_monitor "not firing" | false_positive | its stamp was advancing fine |
| gdrive 439h stale | real | OAuth `invalid_grant` (NOT quota, as assumed) |
| vps 319h stale | real | outpost-us `/` at 100% full |

Manual triage of these took a full session. This ladder finds each in one or two commands.
