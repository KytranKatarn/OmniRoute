"""Unit tests for the hardware-aware node provisioning engine (#3731).
Run: PYTHONPATH=platform_v2 python3 platform_v2/services/test_node_provisioning.py
Pure logic — no network, no DB.
"""

from services.node_provisioning import recommend

_p = _f = 0


def check(desc, cond):
    global _p, _f
    if cond:
        _p += 1
    else:
        _f += 1
        print("FAIL:", desc)


# 1. CPU-only outpost (2c / 8GB) — the singapore/lithuania/uk class
r = recommend(cpu_cores=2, ram_gb=8, gpu_available=False)
check("outpost tier", r.tier == "cpu-outpost")
check(
    "outpost warm set = tiny+embed+3b", set(r.recommended_ollama) == {"qwen2.5:1.5b", "nomic-embed-text", "llama3.2:3b"}
)
check("outpost can't run 7B (prefer_gpu, no GPU)", "qwen2.5:7b" in r.cannot_run_ollama)
check("outpost no ComfyUI", r.recommended_comfyui is None)

# 2. Starship — RTX 3070 8GB / 32GB
r = recommend(cpu_cores=8, ram_gb=32, gpu_available=True, gpu_vram_gb=8, gpu_model="RTX 3070")
check("starship tier gpu-mid", r.tier == "gpu-mid")
check("starship runs 7B", "qwen2.5:7b" in r.can_run_ollama)
check("starship warm includes 7B", "qwen2.5:7b" in r.recommended_ollama)
check("starship ComfyUI = SDXL", r.recommended_comfyui == "sd_xl_base_1.0.safetensors")

# 3. Big GPU 12GB → Flux
r = recommend(cpu_cores=12, ram_gb=64, gpu_available=True, gpu_vram_gb=12)
check("12GB tier gpu-large", r.tier == "gpu-large")
check("12GB ComfyUI = Flux", r.recommended_comfyui == "flux1-dev-fp8.safetensors")

# 4. Light GPU 4GB → SD1.5, no 7B
r = recommend(cpu_cores=4, ram_gb=12, gpu_available=True, gpu_vram_gb=4, gpu_model="RTX 3050")
check("4GB tier gpu-small", r.tier == "gpu-small")
check("4GB ComfyUI = SD1.5", r.recommended_comfyui == "v1-5-pruned-emaonly.ckpt")
check("4GB can't run 7B", "qwen2.5:7b" in r.cannot_run_ollama)
check("4GB runs 3b on GPU", "llama3.2:3b" in r.can_run_ollama)

# 5. Starved node — 2GB RAM, no GPU → can't host anything
r = recommend(cpu_cores=1, ram_gb=2, gpu_available=False)
check("starved warm set empty", r.recommended_ollama == [])
check("starved note flags insufficient RAM", any("Insufficient" in n for n in r.notes))

print(f"PASS={_p} FAIL={_f}")
raise SystemExit(1 if _f else 0)
