FROM python:3.12-slim@sha256:acd871b0cd8a2c5927d8b6e637ef5f5b8e9a882e2dcbaa0e7e41aa4db52c4ea2

WORKDIR /app

# Install system deps for psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --no-create-home --shell /bin/false appuser

COPY pyproject.toml README.md LICENSE ./
COPY kytran_server_manager/ ./kytran_server_manager/

RUN pip install --no-cache-dir .

# Create data dir and set permissions before switching user
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

ENV KSM_HOST=0.0.0.0
ENV KSM_PORT=8080
ENV KSM_DATA_DIR=/data

EXPOSE 8080

VOLUME ["/data"]

CMD ["kytran-system-operations"]
