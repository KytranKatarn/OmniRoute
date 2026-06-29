# Cluster Saturation + K.I.N. Welfare Breakage — Diagnosis (2026-06-08)

Triggered by: roadmap-consolidation pilot (#3788) stalled — exposed cluster saturation.
Owner directive: triage saturation, get cluster to optimal agent capacity, K.I.N. workforce
input, bring Citadel (boston-2) in as a bigger compute helper when not in DR, and fix the
broken K.I.N. wellness-break workflows.

## One-line
WTF's two backlogs flood the dispatch queue; load piles onto CPU outposts while GPU nodes idle;
~½ of jobs fail "no result"; the 34 department agents starve; and the K.I.N. wellness-break
safeguard that should rebalance all this **logs rest cycles but never benches the agent** — so
nothing ever rebalances.

## Evidence
### Node load is inverted (GPU idle, CPU outposts melting)
- Lithuania **42** / Outpost-US **43** (CPU, no GPU, cap 5) — ~8.5× over capacity.
- Citadel 11, Singapore 9.
- Hub (Quadro M4000) **0**, Defiant (RTX 3070) **2**, Runabout (RTX 3050) **2** — GPUs nearly idle.
- Cluster: total_load 111 vs total_capacity 45.
→ Heavy/7B + quick 1.5b jobs are being routed onto CPU outposts that can't run them well,
  while the GPU nodes that should take 7B sit idle. Backwards routing.

### WTF backlogs flood everything
- 1h volume: wtf_hub_quick **284**, wtf_hub **174** (avg **108s**), wtf_dhq_factcheck **74** (avg 118s).
- Both backlogs ON: `work:wtf_factcheck_backlog:enabled=true`, `work:wtf_llm_backlog:enabled=true`.
- These are BACKLOG (reprocessing OLD articles), distinct from live ingest — safe to pause.

### ~½ of jobs fail "no result" (3h)
- bias_quick **310** + factcheck_quick **44** (qwen2.5:1.5b) — CPU outposts choke / time out.
- Dept work also failing: knowledge_analysis 10, documentation 8, code_review 8, creative 8 (mistral:7b).

### Department agents starve
- 43 agents starving; **0 working now, 0 completed today**; all token_usage ≈ 0.
- Severity warning: "22 idle agents (dispatcher routing gap)". The 34 dept agents can't get work
  because the queue is monopolized by WTF.

### K.I.N. wellness-break ENFORCEMENT is broken (owner's flag)
- `agent_rest_cycles`: 15 rests logged in 24h; V.E.R.I.F.Y. (id 116) re-rested every ~30 min
  ("A.R.C.H.I.E. COO 12h work threshold — C.R.E.E.D. mandatory rest"), overlapping 8h windows.
- BUT `shift_state`: **49 AI agents all `active`, 0 in winding_down/cooldown/off_duty/resting.**
- → Rest cycles are RECORDED but the agent is never transitioned off duty and its work is never
  redelegated. The maxed agent keeps working, re-trips the threshold, logs another phantom rest.
  This is why load never moves to idle agents/nodes.

## Remediation (prioritized — owner approval required before any change)
- **P0 — instant relief (reversible toggle):** pause `work:wtf_factcheck_backlog:enabled` +
  `work:wtf_llm_backlog:enabled` via work_control_service. Stops OLD-article reprocessing only
  (live ingest unaffected). Drains the flood immediately.
- **P1 — routing:** stop sending 7B + fact_check onto CPU outposts at load 42; prefer GPU nodes
  (Hub, Starships) for 7B; CPU outposts = light/regional only. Investigate why max_concurrent=5
  is not bounding outpost load, and the node_preference logic for WTF.
- **P2 — K.I.N. welfare enforcement (the owner's safeguard):** rest cycles MUST transition the
  agent's shift_state (winding_down→cooldown) AND trigger redelegation to a peer/another node;
  today it is log-only. Trace the welfare rework (PRs #1466/1467/1478/1479) for the dropped
  shift_state transition.
- **P3 — Citadel (boston-2, 31GB RAM):** enroll as a CPU-7B agent contributor when not in DR.
- **P4:** department-agent starvation should resolve once P0+P1 unjam the queue.

## Constraints honored
- Read-only diagnosis only so far. No config changed. (Claude+infra caution, mistake #250231.)
- escalation_mode=local_only (ADR-004) — not flipping to cloud without owner decision.
- All inference via DHQ dispatcher; mesh-only transport.
