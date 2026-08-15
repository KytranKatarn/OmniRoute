FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    git curl wget libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Install PyTorch with CUDA 11.8 — supports compute 3.7+ (Maxwell M4000 = 5.2)
RUN pip install --no-cache-dir \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# --- PINNED VERSIONS -------------------------------------------------------
# These three repos were cloned UNPINNED (tracking HEAD) until 2026-08-14, so
# every rebuild silently adopted whatever upstream shipped that day. A rebuild
# on ~2026-07-17 did exactly that and moved us to ComfyUI v0.28.0, which broke
# the container with no commit in this repo to blame.
#
# ⚠️ COMFYUI_REF BELOW IS KNOWN-BROKEN ON THIS HARDWARE. It is pinned only to
# make the current (failing) image reproducible — do NOT read it as good.
# v0.28.0 pulls `comfy-aimdo` 0.4.10, which dies with
#   Fatal Python error: Illegal instruction
# right after "[Prompt Server] web root:" on this host (Quadro M4000, compute
# 5.2 Maxwell; image ships torch 2.7.1+cu118 while comfy_kitchen wants cu130+).
# FIX FORWARD: set COMFYUI_REF to the newest release PREDATING comfy_kitchen /
# comfy-aimdo, then rebuild and confirm /system_stats actually answers.
ARG COMFYUI_REF=285a98944c397a4a81f15ac63d69fa3dbc0a27b9
ARG COMFYUI_MANAGER_REF=bd88cffa7166484cbd16c3eba8a5a377a20b01dc
ARG COMFYUI_LTXVIDEO_REF=aceeae9635f6d493f2893ba3c411a1c36031788a

# Clone ComfyUI (pinned — see COMFYUI_REF above)
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /comfyui \
    && git -C /comfyui checkout --detach ${COMFYUI_REF}
WORKDIR /comfyui

# Install ComfyUI requirements
RUN pip install --no-cache-dir -r requirements.txt

# Install ComfyUI Manager (browse/install custom nodes from UI)
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    git -C ComfyUI-Manager checkout --detach ${COMFYUI_MANAGER_REF}

# Install LTX-Video node (Lightricks video generation)
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/Lightricks/ComfyUI-LTXVideo.git && \
    git -C ComfyUI-LTXVideo checkout --detach ${COMFYUI_LTXVIDEO_REF} && \
    cd ComfyUI-LTXVideo && \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# C compiler for triton's runtime JIT. ComfyUI's comfy_kitchen hard-imports the
# triton backend at startup, which compiles a CUDA driver shim (driver.c) on the
# fly — the `-runtime` base image ships no toolchain, so this raised
# "RuntimeError: Failed to find C compiler" before ComfyUI could bind a port.
# Deliberately the LAST layer: the ComfyUI clone above is UNPINNED (tracks HEAD),
# so invalidating its cache would silently roll the app forward on every rebuild.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8188

RUN mkdir -p /comfyui/user/default/workflows

# GPU enabled, disable cuda-malloc for Maxwell compatibility
ENTRYPOINT ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-cuda-malloc"]
