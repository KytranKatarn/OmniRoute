# Coders and reviewers together on the fleet — investigation

**Date:** 2026-09-11 · **Status:** investigation only, no code written
**Asked:** "how could we optimize to allow us to use the nodes better, so that when we are
in aux mode coders and reviewers get priority?"
**Related:** #6662 (named in `fleet_dispatch_profile.py`), #5903, #6081/#6099 (AUX POWER)

---

## ✅ RESOLVED 2026-09-11 08:51 EDT — read this before the rest

**The hub was fixed by `systemctl restart ollama`.** Everything below was written
BEFORE that and describes the fault in the present tense; it is kept as the
investigation record, not as current state.

| after the restart | |
|---|---|
| `qwen2.5-coder:7b` | **3.7s** (was a 420s timeout, 0 successes in 56.7h) |
| `gemma3:12b` | **8.9s** |
| TITAN X | **9.3GB and computing** (was 5.0GB at 0% util) |
| opencode -> hub -> coder | **13.5s** for a full agent turn |

**Root cause:** ollama scheduler state accumulated over 2d16h of uptime — every
model placed on GPU0 (Quadro, 84% full / 96% util) while GPU1 idled with 7.1GB
free, and escaping required evicting a model that continuous traffic never let go
idle. A restart re-decides placement from scratch. KB **#315235**.

**What shipped as a result:** `model_loadability_monitor` + the never-scheduled
`residency_monitor` wired up (PR #3291), a weekly `ollama-weekly-restart.timer`
(Sun 05:30) bounding how long the state can accumulate, and tasks #6686/#6687/#6688.

⚠️ **The placement fix in this PR is correct but was NOT what fixed coding.**
Recorded in decision #1107 so the history cannot be misread later.

---

## The short answer

The placement question is real and worth fixing, but it is **downstream of a live fault**:
right now the hub cannot load *any* model that is not already resident. Until that is
resolved, no warm-pin layout — on starbase, across nodes, or behind OmniRoute — changes the
outcome for coding, because every layout ends in "and then the hub loads the coder model."

The nodes are already the working path. USS-245 serves `qwen2.5-coder:7b` today.

---

## What was measured (and what it ruled out)

Every row below is a live measurement on the hub, not a reading of the code.

| Hypothesis | Test | Result |
|---|---|---|
| The CLIs (codex/opencode) are misconfigured | Direct HTTP, no CLI | Same hang — **not the CLIs** |
| The OpenAI-compat shim `/v1` | `/api/generate`, `/api/chat`, `/v1/chat/completions` | All three identical — **not the endpoint** |
| Tool definitions / streaming | 2×2 with and without each | All four hang — **not tools, not streaming** |
| DHQ / agent management holds models | Direct call bypassing the dispatcher | Same hang — **not DHQ** |
| Model drive went read-only | `/proc/1/mountinfo`, `/proc/<ollama>/mountinfo` | Host + ollama both `rw`; the `ro` reading was **my own Bash sandbox's mount namespace** |
| Disk failing | 300 MB direct read | 259 MB/s, no I/O errors — **disk healthy** |
| VRAM exhausted | Retested with **7.1 GB free** on the TITAN vs 5.5 GB needed | Still hung — **not free-space** |
| `num_ctx` inflating the KV reservation | 2048 / 4096 / 8192 | All hang — **not context size** |
| Model-specific fault | A/B: coder vs `gemma3:12b` (which succeeded 3.7 h earlier) | **Both** hang — not model-specific |
| Model missing/corrupt | `/api/tags` | All present on disk with sane sizes |
| Wedged since a restart | `ps` on the ollama pid | Up **2 d 16 h**, no restart; and it was loading models 3.7 h ago |

**The signature, repeated across every attempt:** ollama returns 200 on the request, then
VRAM never moves by a single MiB for 300 s, no runner process spawns, and nothing is written
to its log — while *resident* models continue serving normally at 0.2–5 s throughout.
`runners=4` is constant against `OLLAMA_MAX_LOADED_MODELS=10`.

So the hub has entered a state where its resident set is **frozen**: what is loaded works,
nothing else can ever load. It is a state, not a config fault — `gemma3:12b` loaded fine
3.7 hours ago on this same process.

### Blast radius (this is not only a coding problem)

`task_execution_log`, 7 days, starbase only:

| model | runs | ok | last success |
|---|---|---|---|
| `qwen25-classify` | 7395 | 7395 | minutes ago |
| `qwen2.5:7b` | 10356 | 9268 | minutes ago |
| `mistral:7b` | 7328 | 6808 | 0.5 h |
| `gemma3:12b` | 2460 | 2241 | 3.7 h |
| `llama3.2:3b` | 41 | 25 | **40.2 h** |
| `qwen2.5-coder:7b` | 28 | 14 | **56.7 h** |
| `dolphin3:latest` | 78 | 35 | **71.7 h** |

Fleet-wide over 24 h, `qwen2.5-coder:7b` is **3 attempts, 0 successes, 401 s average**.
Repair Bay's code-generation path is failing in production and has been for over two days.
Nobody noticed because the high-volume workloads ride the frozen-in residents.

### The hub and USS-246 fail DIFFERENTLY (added after further testing)

Forcing CPU (`options.num_gpu = 0`) separates the two failures cleanly:

| node | default request | `num_gpu:0` |
|---|---|---|
| USS-246 (RTX 3070 8 GB, 4.8 GB occupied) | HUNG 420 s | **200, 128.5 s (126.2 s load), 7.0 tok/s** |
| Hub (20 GB, fragmented free) | HUNG 300 s | **still HUNG 300 s** |
| USS-245 (RTX 3050 4 GB) | loaded (partial GPU) | n/a — already works |

**USS-246 is a GPU-wait deadlock.** It has *almost* enough free VRAM (≈3 GB free, model
needs 5.5 GB), so ollama keeps waiting for an eviction that never arrives because traffic
never lets a runner go idle. Told to skip the GPU, it loads. USS-245 never deadlocks because
its 4 GB card is hopeless for a 7B, so ollama demotes to CPU immediately — which is why it
was the only node that worked all session.

**The hub is NOT that.** It hangs even with the GPU decision removed entirely, so its
scheduler is not dispatching a new runner under any placement. `runners=4` is constant
against a limit of 10.

Config staleness was checked and ruled out: `override.conf` last modified **2026-08-28**,
ollama started **2026-09-08**, so `OLLAMA_MAX_LOADED_MODELS=10` *is* the live value.

### What could not be determined without privilege

- The **running** process env (`/proc/<pid>/environ` needs root) — so `MAX_LOADED_MODELS=10`
  is confirmed only in the unit file, never in the live process.
- Ollama's own scheduling decision — needs `OLLAMA_DEBUG=1`, which needs a restart.

**A restart is the standard remedy for this class and is also the main risk:** it drops all
four residents, and if new loads are still broken afterwards the hub loses *all* inference,
which ~134 active agents depend on. That is an owner decision, not a quiet fix.

---

## The placement fix (worth doing, but second)

Independent of the fault above, the AUX POWER warm-pin wastes half the GPU fleet.

`fleet_jobs.py:404` sets `TOP_K = 1` — each node warms exactly one model — and
`fleet_jobs.py:471-476` pins **the same** focus model to the head of **every** GPU node:

```python
_focus_model = get_focus_warm_model()
if _focus_model and _focus_model in available and n.get("gpu_available"):
    targets = ([_focus_model] + [t for t in (targets or []) if t != _focus_model])[:TOP_K]
```

With `FAMILY_WARM_MODELS["repair_bay"] = "qwen2.5:7b"`, arming AUX gives:

| node | GPU | warm slot | demand on that node (24 h) |
|---|---|---|---|
| USS-246 | RTX 3070 8 GB | `qwen2.5:7b` | but `mistral:7b` runs **837** there vs qwen2.5:7b's 586 |
| USS-245 | RTX 3050 4 GB | `qwen2.5:7b` (cannot fit 4 GB) | `mistral:7b` runs **928** there vs 429 |

So arming AUX today would (a) duplicate one model across both Starships, (b) displace the
model each node actually uses most, and (c) still leave the coder with nothing. All three are
fixable with one small change:

1. **`FAMILY_WARM_MODELS` values become an ordered list** —
   `"repair_bay": ["qwen2.5-coder:7b", "qwen2.5:7b"]` — accepting a bare string for
   back-compat. This is exactly what the `#6662` comment in that file anticipates.
2. **Distribute instead of broadcast.** Walk the focus list against GPU nodes ordered by
   capacity, assigning each model to a node where it fits on GPU (`vram_gb` from
   `services.model_sizes`) and is already present. Keep `TOP_K = 1` — at 5.5 GB per 7B in an
   8 GB card, one per node is correct; the lever is *which* model, not how many.
3. **Never displace a node's demand leader.** Only take a node's slot if the focus model's
   priority beats the demand model's 24 h run count, else fall through to the next node.

Measured footprints (`services.model_sizes`): `qwen2.5:7b`, `qwen2.5-coder:7b` and
`mistral:7b` are **identical** at `vram=5.5, ram=8.0`. `llama3.2:3b` is `vram=3.0, ram=5.0`.
So 5.5 fits USS-246's 8 GB card and cannot fit USS-245's 4 GB.

### Why "put both on starbase" does not work as stated

Starbase has 20 GB across two cards and currently holds ~11.9 GB. There is room on paper.
But `mistral:7b` there is not idle — it serves **12 capabilities**, including
R.O.S.E.T.T.A.'s `translate` at **3.7 s average over 224 runs/day**. Evicting it to make room
trades a fast, high-volume path for a slow one. And the hub cannot load the coder even with
7.1 GB free, so the trade buys nothing today.

### What OmniRoute does and does not solve

OmniRoute is free, self-hosted, already running, and is the right place to put **routing** —
so opencode / archie-tui / codex do not hardcode a backend and can fail over between hub and
Starships. It does **not** create capacity and cannot make a model warm. Useful for the lane,
irrelevant to this fault.

---

## Recommended order

1. **Resolve the frozen residency on the hub.** Needs root (read the live env, enable
   `OLLAMA_DEBUG`) or an ollama restart with the risk stated above. Until this lands,
   Repair Bay code-gen stays at 0 %.
2. **Point the coding lane at USS-245 now** — proven working end to end today
   (`LOCAL_OPENCODE_OK`), ~13 tok/s warm, `keep_alive: 60m` honoured. Slow first turn
   (~3 min: opencode's large system prompt processed on CPU) but real.
3. **Ship the warm-pin distribution fix (#6662).** Small, testable, and makes AUX mode
   actually mean "coders and reviewers both have a home" instead of "one model, twice."
4. **Consider a coder-sized GPU slot on USS-246.** 5.5 GB fits its 8 GB card. This is the
   only path to real-time local coding, and the cost is USS-246's `mistral:7b` slot —
   a genuine trade to decide once (1) is resolved.

---

## Verification for any change made later

Predict before changing, per `.claude/rules/fleet.md`:

```sql
-- per-node × per-model, sheds excluded; run BEFORE and ~30 min AFTER
SELECT COALESCE(r.node_name,'hub') node, t.model_used, count(*) runs,
       count(*) FILTER (WHERE t.success) ok, round(avg(t.duration_ms)/1000.0,1) avg_s
  FROM task_execution_log t LEFT JOIN remote_nodes r ON r.id = t.node_used_id
 WHERE t.created_at > now()-interval '3 hours' AND t.model_used IS NOT NULL
   AND NOT (NOT t.success AND (t.error_message ILIKE '%hub saturated%'
         OR t.error_message ILIKE '%admission cap%'
         OR t.error_message ILIKE '%shed to relieve%'
         OR t.error_message ILIKE '%backpressure%'))
 GROUP BY 1,2 ORDER BY runs DESC;
```

The success criterion for (1) is narrow and unambiguous: **a model outside the resident set
loads on the hub within 120 s.** Probe scripts used in this investigation are in
`$CLAUDE_JOB_DIR/tmp/` (`probe_cross.js`, `coldload_watch.sh`, `ctx_probe.js`, `ab_models.js`).
