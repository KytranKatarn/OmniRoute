FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    git curl wget libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Install PyTorch with CUDA 11.8 — supports compute 3.7+ (Maxwell M4000 = 5.2)
RUN pip install --no-cache-dir \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Clone ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /comfyui
WORKDIR /comfyui

# Install ComfyUI requirements
RUN pip install --no-cache-dir -r requirements.txt

# Install ComfyUI Manager (browse/install custom nodes from UI)
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git

EXPOSE 8188

RUN mkdir -p /comfyui/user/default/workflows

# GPU enabled, disable cuda-malloc for Maxwell compatibility
ENTRYPOINT ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-cuda-malloc"]
