#!/usr/bin/env python3
"""Download SDXL checkpoints for ComfyUI portrait generation."""

import urllib.request
import os
import sys

DEST = "/mnt/data2/comfyui/models/checkpoints/"

MODELS = [
    {
        "name": "RealVisXL_V4.0.safetensors",
        "url": "https://huggingface.co/SG161222/RealVisXL_V4.0/resolve/main/RealVisXL_V4.0.safetensors",
        "desc": "RealVisXL V4 — photorealistic portraits",
    },
    {
        "name": "juggernautXL_v9.safetensors",
        "url": "https://huggingface.co/RunDiffusion/Juggernaut-XL-v9/resolve/main/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "desc": "Juggernaut XL v9 — excellent photorealism",
    },
    {
        "name": "sdxl_turbo.safetensors",
        "url": "https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors",
        "desc": "SDXL Turbo — fast generation",
    },
]


def download(model):
    path = os.path.join(DEST, model["name"])
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000_000:
        print(f"SKIP {model['name']} — already exists ({os.path.getsize(path) / 1e9:.1f}GB)")
        return

    print(f"DOWNLOADING {model['name']} — {model['desc']}")
    print(f"  URL: {model['url']}")
    try:
        urllib.request.urlretrieve(model["url"], path)
        size = os.path.getsize(path) / 1e9
        print(f"  DONE: {size:.1f}GB")
    except Exception as e:
        print(f"  FAILED: {e}")
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    os.makedirs(DEST, exist_ok=True)

    if len(sys.argv) > 1:
        # Download specific model by index
        idx = int(sys.argv[1])
        download(MODELS[idx])
    else:
        # Download all
        for m in MODELS:
            download(m)

    print("\nAll checkpoints:")
    for f in sorted(os.listdir(DEST)):
        if f.endswith((".safetensors", ".ckpt")):
            size = os.path.getsize(os.path.join(DEST, f)) / 1e9
            print(f"  {f} ({size:.1f}GB)")
