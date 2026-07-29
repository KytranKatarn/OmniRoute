> ⚠️ **SUPERSEDED IN PART — hardware changed TWICE after this spec was written. RESOLVED 2026-07-28.**
> §2's baseline assumes **one GPU** (Quadro M4000, 120 W cap) and a **single 600 W PSU**, concluding
> comfortable headroom (~204 W total, 34 % load). Both halves of that premise are now false.
> **Do not act on §2's figures.** The **method** (per-component watts, totals, headroom, history) is
> unchanged and correct; the collector shipped in PR #2443. Only the numbers are stale.
>
> **Change 1 — a second GPU was installed:**
>
> | Idx | GPU | Power limit | VRAM | Compute cap. |
> |---|---|---|---|---|
> | 0 | Quadro M4000 | 120 W | 8 GB | 5.2 |
> | 1 | **NVIDIA TITAN X (Pascal)** | **250 W** | 12 GB | 6.1 |
>
> Identify these cards by **UUID, not index** — the TITAN is idx **1**, not 0. Mixed compute
> capability means a single model **cannot span both cards**; `remote_nodes.gpu_vram_gb` stays **12**
> (largest single card), never the 20 GB sum.
>
> **Change 2 — measured under real load (2026-07-28), then a second PSU was added.**
> Method: 480 `nvidia-smi` samples @ 0.5 s over ~120 s while driving 3 concurrent DHQ dispatches
> (sanctioned path, ADR-013); both GPUs reached 100 % utilisation.
>
> | Card | Idle | Mean | Peak |
> |---|---|---|---|
> | Quadro M4000 (120 W cap) | 13.1 W | 78.1 W | 102.5 W |
> | TITAN X Pascal (250 W cap) | 19.1 W | 77.6 W | 280.3 W |
> | **Combined, same instant** | — | **155.7 W** | **375.5 W** |
>
> 375.5 W is a **simultaneous** measurement, not a sum of independent peaks. The earlier 370 W
> TDP-sum estimate was slightly *low*. The TITAN transiently exceeded its 250 W cap because that cap
> is enforced as an **average**, not an instantaneous clamp (`power.max_limit` is 300 W).
>
> ⚠️ **PRECISION:** only the **GPU** figure is measured. CPU/RAM/disk remain **estimates** — there is
> no wall meter and no BMC on this box, so any "system total" is measured-GPU + estimated-rest.
> This was **LLM inference, not SDXL** — a realistic load, not an absolute worst case.
>
> **Resolution — the hub now has TWO power supplies (owner-installed 2026-07-28):**
>
> | Supply | Model | Rating | Load | Utilisation | Feeds |
> |---|---|---|---|---|---|
> | PSU1 | Delta DPS-600UB rev 05 | 600 W | 314.5 W | **52.4 %** | board, CPU, RAM, disks, fans, PCIe **slot** power |
> | PSU2 | Enermax Galaxy EVO | 1050 W | 225.5 W | **21.5 %** | the video cards only |
>
> ⚠️ **Two PSUs do NOT pool into one budget.** Each has its own ceiling, and PCIe **slot** power
> (up to 75 W per card) is drawn from the motherboard = **PSU1**, regardless of which supply feeds
> the 6/8-pin cables. With two cards PSU1 still carries ~150 W of GPU draw even though "the GPUs are
> on PSU2". Never quote the 1650 W installed total as available headroom.
>
> Cabling is correct and owner-confirmed: **one dedicated cable per GPU** from PSU2, not daisy-chained
> off a single splitter. KSO reports all of the above live (`psu_count=2`, binding PSU1).
>
> **The "~500 W against a 600 W supply" alarm in the original banner is retired** — that conclusion
> assumed a single supply. At 52.4 % / 21.5 % there is no PSU-driven blocker to further GPU load, and
> **no PSU upgrade is required.**
>
> **Rail layout — CONFIRMED by the owner 2026-07-29: the two GPU cables sit on SEPARATE 12 V rails,**
> and that separation was deliberate. This matters because the Enermax Galaxy EVO is a **multi-rail**
> unit: total wattage is not the only ceiling, since a per-rail OCP can trip well below the unit's
> rating. With the cards on distinct rails, each cable carries roughly **113 W** of the ~225 W that
> PSU2's cables see at the measured peak (375.5 W combined GPU **minus** up to 150 W of PCIe slot
> power, which is drawn from PSU1) — inside a single 8-pin connector's 150 W rating, and far inside
> any plausible rail OCP on a 1050 W supply. The pathological case for a multi-rail unit — two cards
> sharing one connector's rail via a daisy-chained splitter — is structurally impossible here.
>
> **No open hardware questions remain.** Task **#5366** is complete. KSO's own PSU reporting is
> **#5368**; the latent multi-GPU parse in KSO's container-dead `get_gpu_info()` fallback is **#5399**.

# KSO Power Monitoring — Spec (2026-07-23)

**Product:** Kytran System Operations (KSO) — standalone, port 8085, server.kytranempowerment.com,
source `/mnt/archie_brain/kytran-server-manager/`, host-side agent `host_monitor.py`.
**Owner ask:** measure total watts the hub server draws, so we can decide whether the **600 W PSU**
is adequate, plan a **GPU upgrade**, and whether **both PCIe slots** can be populated.

---

## 1. Motivation / decision this must serve
The real question is PSU headroom: *how many watts is the box drawing, and how much is left under
the 600 W supply for a bigger or second GPU?* Today nothing measures this. KSO should collect
per-component watts, total them, show PSU headroom, and keep a history so we can see load spikes
before buying hardware.

## 2. Hardware baseline (measured on the hub 2026-07-23)
| Component | Detail | Power |
|---|---|---|
| GPU | Quadro M4000 (8 GB), 1 card, PCIe 05:00 | **102 W measured**, 120 W hard cap |
| CPU | Intel Xeon **E5-2658 v2** (Ivy-EP, 10c/20t, LGA2011) | 95 W TDP |
| RAM | 128 GB DDR3 ECC RDIMM | ~30 W (est.) |
| Disks | multiple (see `lsblk`) | est. per device |
| PSU | 600 W | — |
| Board/VRM/fans | server board | ~40–60 W (est.) |
Sensors present: **nvidia-smi (GPU watts)**, **Intel RAPL (CPU watts)**. Absent: lm-sensors, UPS/NUT,
IPMI/BMC — so **no wall-power reading exists today**.

## 3. Data sources — MEASURED vs ESTIMATED (honesty is a hard requirement)
KSO must visibly label each figure. Do NOT present an estimate as a measurement.

| Component | Source | Class | Notes |
|---|---|---|---|
| GPU | `nvidia-smi --query-gpu=power.draw,power.limit,power.max_limit` (per card → scales to 2 GPUs) | **measured** | host_monitor.py already calls nvidia-smi (line ~1221) — just add the power fields |
| CPU | RAPL: sample `/sys/class/powercap/intel-rapl:0/energy_uj` twice, `ΔμJ / Δt` → W | **measured** | ⚠️ `energy_uj` is **root-read only** (RAPL side-channel lockdown). host_monitor runs host-side; needs root or a sudo bridge. Handle `intel-rapl:0` package + roll up sub-domains. Handle 64-bit counter wraparound (`max_energy_range_uj`). |
| RAM | `dmidecode -t memory` → populated DIMM count × per-DIMM watt (DDR3 ECC RDIMM ≈ 3–4 W) | **estimated** | no RAM watt sensor exists anywhere; model only. dmidecode needs root. |
| Disks | reuse `get_disk_layout()` (lsblk) → per device by type: SSD ≈ 2–3 W active / ~0.1 idle; HDD ≈ 6–9 W active / ~4 idle; NVMe ≈ 3–6 W active | **estimated** | refine active/idle from per-disk `%util` if cheap; otherwise assume a duty factor |
| Board+VRM+fans | fixed configurable baseline (~50 W default for this board) | **estimated** | single tunable in config |
| **Wall total (v2)** | smart plug (Kasa/Shelly HTTP) or UPS (NUT `upsc`) | **measured** | the ONLY true total; when present it OVERRIDES the modeled total |

**Estimated total (v1)** = CPU(meas) + GPU(meas) + RAM(est) + disks(est) + baseline(est).
**Measured total (v2)** = wall meter, if configured.

## 4. Architecture (extend, don't rebuild)
- **Collection:** extend `host_monitor.py` with a `get_power()` returning `{per_component:[{name, watts,
  max_watts, class:'measured'|'estimated', detail}], total_watts, total_class, psu_watts:600,
  headroom_watts, headroom_pct}`. Reuse existing GPU + disk collection.
- **Sampling + history:** a periodic sampler (e.g. every 10–30 s) writes a row to KSO's SQLite
  (`power_samples(ts, component, watts, class)` + a rolled-up `power_totals(ts, total_watts, class)`).
  Retention: keep raw ~7 d, downsample older to hourly (mirror how other KSO history is stored).
- **API:** `GET /api/power/current` (live snapshot), `GET /api/power/history?range=1h|24h|7d`
  (time-series), `GET /api/power/psu` (headroom + upgrade budget).

## 5. UI (matches owner's structure)
- **Hardware tab** — existing inventory + a new **"power / potential"** column per component:
  `current W / max W` (GPU 102/120, CPU RAPL/95, etc.) = per-component headroom, with a measured/est. tag.
- **Per-component tabs** (CPU / GPU / Memory / Storage) — each shows its own live watts + mini-trend.
- **Dashboard** — the totals view:
  - Big **total watts** (measured if wall meter, else "≈ estimated").
  - **PSU headroom gauge**: current draw vs 600 W with an **80% redline** (never size a PSU to 100%).
  - **kWh + $/mo** (configurable $/kWh).
  - **GPU-upgrade budget**: watts left under the 80% line = "you can add up to ~N W of GPU."
- **Watts history chart** — stacked-area per component + a total line, range 1h/24h/7d. This is where a
  load spike (e.g. M4000 hitting 120 W under SDXL) becomes visible before buying hardware.

## 6. The PSU / upgrade guidance the dashboard should encode
Budget box-without-GPU ≈ 240 W; keep sustained ≤ **80% of 600 W = 480 W**.
| Scenario | est. total | vs 600 W | verdict |
|---|---|---|---|
| current (1× M4000) | ~360 W | 60% | ✅ fine |
| 2× M4000 (both slots) | ~480 W | 80% | ⚠️ tight — prefer 750 W |
| 1× ≤170 W card (3060/4060) | ~410 W | 68% | ✅ fine |
| 1× 300 W+ card (3090/4090) | 640–740 W | >100% | ❌ needs 850 W+ |
| 2× mid cards | ~580 W | 97% | ❌ needs 850 W |
Extra gates: (a) PSU must physically have enough 6/8-pin **PCIe connectors**; (b) confirm the board
has two usable x16 slots with spacing (E5-2658 v2 = 40 PCIe 3.0 lanes; slot count is board-specific —
verify with `dmidecode -t slot`/`-t baseboard`).

## 7. Phasing
- **v1 (software-only, no hardware needed):** GPU (measured) + CPU RAPL (measured) + RAM/disk/baseline
  (estimated) → live total, PSU headroom gauge, history chart, per-component tabs. Clearly labelled est.
- **v2 (accurate total):** add a smart plug (TP-Link Kasa KP125M / Shelly Plug S, ~$20) or a UPS+NUT;
  KSO polls it and shows a **measured** wall total that overrides the estimate. This is the number that
  actually settles the 600 W / upgrade decision.

## 8. Implementation notes / gotchas
- RAPL `energy_uj` root-only → host_monitor needs privilege or a narrow sudo entry. Fail gracefully to
  "CPU watts unavailable (needs root)" rather than a fake number.
- nvidia-smi `power.draw` is per-GPU — iterate all cards so a 2nd GPU is picked up automatically.
- Never mix measured + estimated silently; every figure carries its class in the API + UI.
- KSO deploy is image-baked (`docker compose up -d --build`, pip-install gotcha: source loads from
  site-packages AND /app/ — hot-patch both). See capability index KSO entry.

## 9. Acceptance criteria
1. `GET /api/power/current` returns real GPU watts (matches `nvidia-smi`) and real CPU watts (RAPL),
   with RAM/disk/baseline estimates, each tagged measured/estimated.
2. Dashboard shows total + PSU headroom gauge (80% redline) + GPU-upgrade budget.
3. History chart renders per-component + total over 1h/24h/7d from persisted samples.
4. Hardware tab shows per-component current/max power.
5. If a wall meter is configured (v2), the measured total overrides the estimate and is labelled measured.

## 10. Open questions for owner
- Is there a smart plug / UPS on that outlet already, or is v1 software-only the starting point?
- Board model (for exact slot count / PCIe spacing) — confirm via `dmidecode` when we build.
- $/kWh for the cost figure.
