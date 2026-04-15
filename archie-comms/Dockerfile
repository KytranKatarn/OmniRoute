FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r archie && useradd -r -g archie -m archie

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R archie:archie /app

USER archie

EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3002/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:3002", "--workers", "2", "--timeout", "120", "app_comms:app"]
