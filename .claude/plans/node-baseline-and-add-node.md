# "Node Done Correctly" + Smooth +Add Node — complete deploy spec (project #371)

Goal: a `+Add Node` (A.R.M.A.D.A. tab) that produces a fully-correct node in one
smooth, trouble-free pass — **everything set at deploy time**, connected to the
mesh, DR-aware, hardware-right, and resource-bounded. No post-hoc hand-patching.

## ✅ Confirmed baseline (proven on Singapore 2026-06-03)
A correct Linux node =
- **node_api** (docker-compose.vps.yml): `mem_limit 768m` + `cpus 0.5`, `HUB_URL`=mesh
  `http://100.64.0.4:3000` (NEVER public hostname), `DR_HUB_URL`=`http://100.64.0.10:3000`,
  healthcheck green, port 3001 mesh-only (UFW 100.64.0.0/10).
- **archie_outpost_sync** (generated run): `--memory 128m --cpus 0.25`, runs the current
  `node_sync.py` (which has node-side **DR auto-failover** to boston-2), heartbeats 60s.
- **Mesh:** Headscale-joined, stable mesh IP; heartbeat advertises cpu/gpu/ram/ollama_models.
- **AI:** native Ollama on host (small CPU models), `OLLAMA_MAX_LOADED_MODELS` bounds agent RAM.
Singapore verified: node_api healthy 768MB/0.5c + DR env; sync 128MB; hub shows
`online, heartbeat <60s`, 8 ollama models advertised.

## The complete +Add Node deploy must set, AT DEPLOY TIME:
1. **Resource baseline** — bounded node_api + sync (above). ✅ in templates now.
2. **Mesh connect** — Headscale join, mesh IP, mesh-only HUB_URL/BRIDGE_URL. ✅
3. **DRP-flip solution** — DR_HUB_URL so the node self-fails-over to boston-2 if the hub dies. ✅
4. **Hardware-aware model provisioning** — THE LOST WIZARD (below). ⬜
5. **OTA path** — node fetches code/model updates from hub without SSH. ✅ exists; verify wired.
6. **Reach / egress** — node advertises egress capability (#2881/#2884) for distributed fetch. ⬜
7. **Resource governance reported up** — node’s budget (host+agent_reserve+products) visible to
   KSO control plane (#3688 / #2516). ⬜

## #4 — Hardware-aware onboarding wizard (recover, don't rebuild)
At onboarding, detect the node's hardware and provision the right models:
- **Detect:** CPU cores, RAM, GPU model + VRAM (heartbeat already sends `gpu_model`,
  `gpu_vram_gb`, `ram_gb`).
- **Decide tier (existing logic):**
  - Ollama: outpost CPU-only → qwen2.5:1.5b + llama3.2:3b + embed (≤4GB); GPU 8GB → +7B; etc.
    (config in KB #267335, fleet model tiers).
  - ComfyUI: `_select_best_model_for_node()` (KB #240991) — 12GB→Flux, 8GB→SDXL, 4GB→SD1.5.
  - Placement helper: `ollama_options.build_options()` (KB #258190, ollama_options.py).
- **Download:** pull the chosen Ollama models (+ ComfyUI checkpoints if GPU) via the OTA
  model-pull path — "download all the items you need from ollama to comfyui," bounded to
  what the hardware can actually run.
- **Surface:** show the wizard in the +Add Node UI (what it CAN / CAN'T run + what it pulled).

Existing pieces to wire (NOT lost): `_select_best_model_for_node` (#240991),
`ollama_options.py` (#258190), GPU/VRAM awareness (#69421), fleet tiers (#267335).

## Open tasks (#371)
- Hardware-aware +Add Node wizard (this doc #4) — NEW.
- Complete-deploy checklist enforcement (1–7 all set at deploy) — NEW.
- #2516 resource inventory → routing · #3688 KSO control plane · #3437/#3466/#3467 Windows
  onboarding · #2881/#2884 egress/reach · #3230 ARMADA map.

## Rollout
1. Templates correct ✅ (committed). 2. Wizard + complete-deploy enforcement (build).
3. Re-baseline existing nodes from the corrected deploy (after the hub move).
4. Clean-room +Add Node test on a throwaway VPS (truly full deploy, not on a quorum node).

*2026-06-03 — Singapore baseline proven; wizard pieces recovered from KB; vision captured so it can't get lost again.*
