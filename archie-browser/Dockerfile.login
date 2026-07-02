# archie_browser_login (#3953) — the S.I.G.N.A.L. one-time-login surface.
# SAME base + SAME `playwright install chromium` as the worker Dockerfile so
# the headed login and the headless replay share an identical Chromium build
# (= identical device fingerprint, which is what survives LinkedIn step-up).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
# Worker runtime libs + the headed/X stack (Xvfb, VNC, noVNC)
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 \
    xvfb x11vnc novnc websockify \
    libx11-6 libx11-xcb1 libxcb1 libxext6 libxcursor1 libxi6 libxtst6 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY login_app.py login_browser.py headed_tasks.py entrypoint-login.sh ./
# #4649 slice 2 — the generic headed runner executes the SAME baked skills as
# the headless worker (worker-parity discovery via SKILL_NAME attrs).
COPY skills/ ./skills/
RUN chmod +x /app/entrypoint-login.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 4280 4281
CMD ["/app/entrypoint-login.sh"]
