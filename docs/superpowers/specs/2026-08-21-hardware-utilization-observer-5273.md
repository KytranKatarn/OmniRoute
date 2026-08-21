# Hardware Utilization Observer (#5273)

**Status**: spec · **Raised to pri 8** after the #5903 hunt · **Project #380**
**Written**: 2026-08-21, from live inspection of `platform_v2/services/model_service.py`

## Why this is the force multiplier

The #5903 investigation (hub 7B timeouts) burned **four hypotheses** — VRAM exhaustion, dead
Ollama, CPU demotion, slot leak — and hours of hand-querying, to arrive at a fact that a single
`SELECT` would have returned: *placement, not the admission gate, was moving the number.*

It is also the only way to know whether a future orchestration change worked. Today the answer to
"did we start CPU-demoting more often this week?" is `docker logs archie_scheduler | grep placement`
— a ring buffer, not a history. Restart the container and the evidence is gone.

## The key finding: the data already exists, it just isn't persisted

`model_service.gpu_placement_options(model)` describes itself as **"THE single placement decision
point, with one log line per call"**. That is accurate — and it means this observer needs **no new
probing, no new polling, and no node-agent changes**. Every field is already computed there.

Its five branches, all currently log-only:

| # | decision | reason | fields already in hand |
|---|---|---|---|
| 1 | `gpu` | already resident | `resident_vram_gb` |
| 2 | `cpu` | ComfyUI awake — GPUs reserved for image gen | — |
| 3 | `gpu` | budget >= needed | `budget`, `needed` |
| 4 | `cpu` | budget < needed | `budget`, `needed` |
| 5 | `cpu` | VRAM state unknown (exception) | the exception |

Branch 5 is the fail-open path and is the one most worth counting: a silent, exception-driven CPU
demotion is indistinguishable from a deliberate one in the logs, and on this pre-AVX2 Xeon a 7B on
CPU **cannot** finish inside the 240s/300s deadline — it is a guaranteed failure, not a slow path
(see the 2026-08-15 incident, task #5623, and the comment block at `model_service.py:56-64`).

## Phase 1 — persist the placement decision (small, do this first)

**One INSERT at the existing decision point.** New table:

```sql
CREATE TABLE model_placement_log (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    model          TEXT        NOT NULL,
    decision       TEXT        NOT NULL,   -- 'gpu' | 'cpu'
    reason         TEXT        NOT NULL,   -- 'resident' | 'comfyui_reserved' | 'budget_fit'
                                           -- | 'budget_short' | 'vram_unknown'
    budget_gb      NUMERIC(6,2),           -- NULL where the branch does not compute it
    needed_gb      NUMERIC(6,2),
    resident_vram_gb NUMERIC(6,2),
    node_name      TEXT,                   -- hub today; carried for when this generalises
    detail         TEXT                    -- exception text on 'vram_unknown', else NULL
);
CREATE INDEX idx_mpl_created ON model_placement_log (created_at DESC);
CREATE INDEX idx_mpl_model_created ON model_placement_log (model, created_at DESC);
```

### Non-negotiables

- **The write must never break placement.** Wrap in its own `try/except` and let placement proceed
  on failure. An observer that can fail a dispatch is worse than no observer.
- **Do NOT swallow to `logger.debug`.** That is precisely how `mission_revert_at` (#5902) and
  W.A.R.D.E.N.'s integrity check (#2366) became *unmonitored while appearing monitored*. Log a
  `warning` on write failure.
- **Keep the existing log lines.** They are the live debugging surface; this is additive.
- Retention: add to `dispatch_retention_service._TABLES` (age-only, ~30d) — it is append-only and
  will grow. A table with a policy but no pruner is the `vps`-tier bug (#5616) and the gdrive bug
  (#5092), twice already.

### The queries it unlocks (state these before building — if you cannot, do not build)

```sql
-- CPU-demotion rate by model, by hour — the #5903 question, answered in one query
SELECT date_trunc('hour', created_at) hr, model,
       count(*) FILTER (WHERE decision='cpu') cpu,
       count(*) total,
       round(100.0*count(*) FILTER (WHERE decision='cpu')/count(*),0) cpu_pct
  FROM model_placement_log WHERE created_at > now()-interval '24 hours'
 GROUP BY 1,2 ORDER BY 1 DESC, cpu_pct DESC;

-- the fail-open branch: how often is placement guessing?
SELECT count(*), max(created_at) FROM model_placement_log
 WHERE reason='vram_unknown' AND created_at > now()-interval '7 days';

-- correlate placement with outcome (join on model + time bucket)
```

## Measured volume + a preview of the payoff (2026-08-21, 6h of scheduler logs)

**324 calls in 6 hours ≈ 54/hour ≈ 1,300/day.** At 30d retention that is ~39k rows — the table is
cheap and needs no partitioning. Sizing settled; do not over-engineer it.

The same 6h window already shows what the table would make queryable forever:

| model | gpu | cpu | CPU-demotion rate |
|---|---|---|---|
| `qwen25-classify` | 142 | 81 | **36%** |
| `mistral:7b` | 42 | 2 | 5% |
| `qwen2.5:7b` | 31 | 10 | **24%** |
| `gemma3:12b` | 0 | 3 | **100%** |
| `qwen2.5-coder:7b` | 0 | 3 | **100%** |

`gemma3:12b` at 100% CPU is consistent with needing 15.6 GB against a 12 GB largest card.

### ⚠️ A PLACEMENT IS PER-LOAD, NOT PER-REQUEST — record events, derive DURATION

This is the refinement that makes the table worth more than a counter. `gpu_placement_options` is
called when a model is (re)loaded, not on every inference, and `KEEP_ALIVE=60m`. So **10 CPU
placements of a 7B do not mean 10 slow requests — they mean the model sat in CPU mode for some
span, serving every request that arrived during it.** On this pre-AVX2 Xeon each of those is a
guaranteed deadline failure, not a slow path.

Therefore the useful metric is **time-in-state**, derived from consecutive events per model:

```sql
-- fraction of wall-clock each model spent in CPU mode
SELECT model, decision,
       sum(next_at - created_at) AS time_in_state
  FROM (SELECT model, decision, created_at,
               lead(created_at) OVER (PARTITION BY model ORDER BY created_at) AS next_at
          FROM model_placement_log
         WHERE created_at > now() - interval '7 days') t
 WHERE next_at IS NOT NULL GROUP BY 1,2 ORDER BY 1, 3 DESC;
```

Count alone would have understated this badly. Do not ship only a count.

### Relation to #5903 — corroborates, does not overturn

The #5903 write-up lists CPU demotion among the four ruled-out hypotheses. This data is consistent
with that: 10 CPU placements of `qwen2.5:7b` in 6h cannot by themselves account for 449 failures in
10h, so CPU demotion is real but is **not the dominant cause**. The time-in-state query above is
what would settle its true contribution — which is precisely the point of building this.

## Phase 2 — per-card occupancy sampling (bigger, separate task)

Measured today: `remote_nodes.gpu_vram_gb` holds the **largest single card** (hub 12, USS-246 8,
USS-245 4); only the hub carries `extra_capabilities.gpu_vram_total_gb` (20). CPU-only nodes are
correctly NULL. So per-card *occupancy over time* is genuinely absent and needs a heartbeat
extension — do not conflate it with Phase 1.

⚠️ Phase 2 matters because a model **can span both hub cards** (Ollama does it routinely:
`GPULayers:49[Quadro Layers:31, TITAN Layers:18]`), and a spanning model eats headroom on **both**
at once, which placement does not anticipate. That is what drove the VRAM budget to 0.0 GB on
2026-08-15. A single aggregate number cannot show it; you need per-card samples.

## Sequencing

Build **before** wiring Fleet Command (#5902). Fleet Command changes what runs where; without this,
its effect is unmeasurable, and per `.claude/rules/fleet.md` step 6 an unmeasurable change is a guess.
