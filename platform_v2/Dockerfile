FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Docker CLI for sandbox management.
# tzdata provides the IANA timezone database so APScheduler / zoneinfo
# can resolve America/Toronto — the consciousness scheduler crashes on
# boot without it (ZoneInfoNotFoundError).
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    git \
    curl \
    pst-utils \
    pff-tools \
    tzdata \
    espeak-ng \
    tesseract-ocr \
    tesseract-ocr-por \
    tesseract-ocr-fra \
    iproute2 \
    ufw \
    auditd \
    net-tools \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    ffmpeg \
    fonts-dejavu-core \
    rsync \
    openssh-client \
    && curl -fsSL https://get.docker.com -o get-docker.sh \
    && sh get-docker.sh \
    && rm get-docker.sh \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download spacy en_core_web_sm during build — required by TTS (Coqui).
# Without this, TTS triggers a runtime pip install that fails on the
# read-only rootfs (compliance: read_only: true in docker-compose.yml).
RUN python -m spacy download en_core_web_sm

# Install Playwright + Chromium to /opt (not /root/.cache which is tmpfs at runtime)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN playwright install chromium --with-deps

# Copy application
COPY . .

# Create templates directory
RUN mkdir -p templates

# Expose port
EXPOSE 3000

# Run application
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "2", "--timeout", "300", "app:app"]
