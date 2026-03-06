FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ollamadiffuser

EXPOSE 11435

# Models are pulled at first run and cached in the volume
ENTRYPOINT ["bash", "-c", "ollamadiffuser pull stable-diffusion-1.5 && ollamadiffuser pull realvisxl-v4 && ollamadiffuser serve --host 0.0.0.0 --port 11435"]
