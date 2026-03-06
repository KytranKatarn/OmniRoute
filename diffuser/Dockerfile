FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (smaller, no CUDA needed for Maxwell GPU)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install ollamadiffuser on top of CPU torch
RUN pip install --no-cache-dir ollamadiffuser

ENV CUDA_VISIBLE_DEVICES=""

EXPOSE 11435

# Models are pulled at first run and cached in the volume
ENTRYPOINT ["bash", "-c", "ollamadiffuser pull stable-diffusion-1.5 && ollamadiffuser pull realvisxl-v4 && ollamadiffuser serve --host 0.0.0.0 --port 11435"]
