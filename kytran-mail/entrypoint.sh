#!/usr/bin/env bash
set -e

# Substitute env vars into Stalwart config template
envsubst < /opt/stalwart-mail/etc/config.toml.template > /opt/stalwart-mail/etc/config.toml

# Start Stalwart in background
/opt/stalwart-mail/bin/stalwart-mail --config /opt/stalwart-mail/etc/config.toml &
STALWART_PID=$!

# Wait for Stalwart API to be ready
echo "[Kytran Mail] Waiting for Stalwart..."
for i in $(seq 1 30); do
    if curl -sk https://localhost:443/api/principal -u "admin:${MAIL_ADMIN_PASSWORD}" > /dev/null 2>&1; then
        echo "[Kytran Mail] Stalwart ready."
        break
    fi
    sleep 2
done

# Start Flask dashboard
echo "[Kytran Mail] Starting dashboard on :8025..."
cd /app/dashboard
exec gunicorn --bind 0.0.0.0:8025 --workers 2 --threads 2 --timeout 120 "app:create_app()" &
FLASK_PID=$!

# Wait for either process to exit
wait -n $STALWART_PID $FLASK_PID
exit $?
