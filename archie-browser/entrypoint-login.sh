#!/bin/bash
# archie_browser_login entrypoint (#3953): X stack + noVNC + supervisor.
# Cheap at idle — no Chromium runs until login_app /start.
set -e

export DISPLAY=:99

# Clear any stale X lock/socket from a previous run. /tmp survives a
# `docker compose restart`, so a leftover /tmp/.X99-lock makes Xvfb refuse
# display :99 → x11vnc then dies defunct with no display → noVNC "failed to
# connect" while the page still loads (websockify stays up on :4280). This
# silently broke S.T.R.I.N.G.E.R. onboarding after a sidecar restart.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Virtual display for the headed login browser
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &

# Wait for Xvfb to own :99 before starting x11vnc — avoids a boot race where
# x11vnc attaches to a not-yet-ready display and exits defunct.
for _ in $(seq 1 40); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.25
done

# VNC server — password REQUIRED (no-auth VNC would expose the owner's live
# logged-in LinkedIn session to anyone who can reach the port). Fail closed.
if [ -z "${BROWSER_VNC_PASSWORD}" ]; then
    echo "FATAL: BROWSER_VNC_PASSWORD must be set — no-auth VNC is not allowed" >&2
    exit 1
fi
mkdir -p /root/.vnc
x11vnc -storepasswd "${BROWSER_VNC_PASSWORD}" /root/.vnc/passwd
# -localhost: x11vnc accepts connections only from inside the container, so the
# in-container websockify is the ONLY path in (it still enforces -rfbauth).
x11vnc -display :99 -forever -shared -rfbport 5900 -localhost -rfbauth /root/.vnc/passwd &

# noVNC web client on :4280 → VNC :5900
websockify --web=/usr/share/novnc 4280 localhost:5900 &

# Supervisor API on :4281 (start/stop/status of the headed login browser)
exec python3 /app/login_app.py
