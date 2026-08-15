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
# COMFYUI_REF = v0.28.0-5. Previously annotated here as "KNOWN-BROKEN", blaming
# comfy-aimdo / comfy_kitchen. That was WRONG and the correction is worth keeping:
# the SIGILL was never ComfyUI's version. It was `kornia_rs` >= 0.1.11 (see the
# kornia_rs pin below). comfy_aimdo imports fine on this host, and comfy-kitchen/
# comfy-aimdo ship as far back as v0.19.1 — so the "roll back to a release before
# comfy_kitchen" plan would have rolled back many versions and still crashed.
# Diagnose the ACTUAL faulting import (python -X faulthandler) before assuming a
# version rollback is the fix.
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

# --- kornia_rs: the hub CPU cannot execute the newer wheels -----------------
# ComfyUI startup imports kornia (comfy_extras/nodes_post_processing.py), which
# imports kornia_rs — a RUST extension. Wheels >= 0.1.11 are built for a newer
# x86-64 microarch level than this host provides, so the import died with
#   Fatal Python error: Illegal instruction
# during init_extra_nodes, before ComfyUI ever bound a port.
#
# The hub is an Intel Xeon E5-2658 v2 (Ivy Bridge, 2013): `avx f16c`, but NO
# AVX2 and NO FMA. Measured boundary on THIS host — 0.1.14/0.1.13/0.1.12/0.1.11
# all SIGILL (exit 132); 0.1.10 imports clean and works with kornia 0.8.2.
#
# ⚠️ This is a HUB-ONLY constraint. Starship-246/245 run the same ComfyUI and
# the same wheels fine — their CPUs have AVX2. Do NOT "fix" the fleet nodes.
# ⚠️ NOT a ComfyUI-version problem: comfy-kitchen/comfy-aimdo ship as far back
# as v0.19.1 and import fine here. Rolling ComfyUI back would NOT have fixed it.
#
# The import check runs in the SAME layer as the install so a regression fails
# the BUILD loudly, rather than producing an image that crash-loops at runtime.
ARG KORNIA_RS_REF=0.1.10
RUN pip install --no-cache-dir "kornia_rs==${KORNIA_RS_REF}" \
    && python -c "import kornia, kornia_rs; print('kornia', kornia.__version__, '| kornia_rs', kornia_rs.__version__)"

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
