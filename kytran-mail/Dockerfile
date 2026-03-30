FROM stalwartlabs/mail-server:v0.11.8 AS stalwart

FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gettext-base ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Stalwart binary and default config
COPY --from=stalwart /opt/stalwart-mail/bin/ /opt/stalwart-mail/bin/
COPY --from=stalwart /opt/stalwart-mail/etc/ /opt/stalwart-mail/etc/

# Create data directories
RUN mkdir -p /opt/stalwart-mail/data /opt/stalwart-mail/dkim /opt/stalwart-mail/certs /opt/stalwart-mail/logs

# Install Python deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy dashboard app
COPY dashboard/ /app/dashboard/

# Copy config template + entrypoint
COPY config.toml.template /opt/stalwart-mail/etc/config.toml.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ports: SMTP(25), Submission(587), SMTPS(465), IMAPS(993), Sieve(4190), Dashboard(8025), Admin(443)
EXPOSE 25 587 465 993 4190 8025 443

# Data volume
VOLUME ["/opt/stalwart-mail"]

ENTRYPOINT ["/entrypoint.sh"]
