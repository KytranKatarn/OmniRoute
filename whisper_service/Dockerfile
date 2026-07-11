FROM python:3.11-slim

# ffmpeg decodes webm/ogg (browser MediaRecorder) into PCM for faster-whisper.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py gunicorn.conf.py ./

ENV WHISPER_MODEL=base PORT=8090
EXPOSE 8090

# gunicorn.conf.py preloads the model at worker boot (warm/always-loaded).
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
