# GPU TTS sidecar — runs on a fleet GPU node (e.g. Starship-246, RTX 3070 Ampere).
# The pytorch base ships a CUDA 12.1 torch that supports Ampere and works with the
# node's driver; Kokoro rides that torch straight onto the GPU. (The hub's Quadro
# M4000 is Maxwell + a CUDA-13 torch mismatch, which is why voice lives on a node.)
# torch >= 2.4 is REQUIRED — Kokoro's transformers dep refuses to load its model on
# older torch ("PyTorch >= 2.4 is required"), so pin a 2.5 CUDA-12.1 base.
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

# espeak-ng = Kokoro/misaki G2P fallback for out-of-vocabulary words.
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py gunicorn.conf.py ./

ENV ARCHIE_VOICE_BLEND="af_heart,af_jessica" KOKORO_LANG=a PORT=8092
EXPOSE 8092

# gunicorn.conf.py preloads + warms the pipeline on the GPU at worker boot.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
