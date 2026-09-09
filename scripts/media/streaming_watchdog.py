#!/usr/bin/env python3
"""Host-side streaming-engine watchdog (Jellyfin + Plex).

WHY THIS EXISTS (2026-07-08): Jellyfin's web server (Kestrel) hung — the
container stayed "up", Docker reported "healthy" (its healthcheck only watches
the PROCESS, not the HTTP port), background scans kept running, but ZERO ports
were listening, so streaming was dead for hours with no alert. M.A.V.E.N. (the
Media Hub health agent) runs INSIDE the read-only ``mediahub_app`` container,
which has no docker CLI and no docker socket, so it can DETECT a hung engine
but cannot RESTART it. This watchdog runs on the HOST (where docker + the
network live), HTTP-checks each engine's real endpoint, and restarts a
hung-but-running container, then notifies A.R.C.H.I.E.

``restart: unless-stopped`` on the containers only covers a CRASH or a reboot —
not a hung process that keeps the container "up". This closes that gap.

Install: cron every 5 min (see scripts/media/media-streaming-watchdog.cron).
"""
import json
import os
import re
import subprocess
import urllib.request

HUB = os.getenv("ARCHIE_HUB_URL", "http://192.168.1.200:3000")

ENGINES = [
    {"name": "Jellyfin", "container": "media_jellyfin", "url": "http://127.0.0.1:8096/System/Info/Public"},
    {"name": "Plex", "container": "media_plex", "url": "http://127.0.0.1:32400/identity"},
]


def _internal_key() -> str:
    """ARCHIE_INTERNAL_API_KEY from env, else the root .env (so the key never
    has to live in the crontab). Notify is best-effort; the restart still runs
    without it."""
    k = os.getenv("INTERNAL_API_KEY_SCRIPTS") or os.getenv("ARCHIE_INTERNAL_API_KEY", "")  # #6657 scoped caller key
    if k:
        return k
    try:
        with open("/mnt/archie_brain/.env", encoding="utf-8") as fh:
            m = re.search(r"^ARCHIE_INTERNAL_API_KEY=(.+)$", fh.read(), re.M)
            return m.group(1).strip() if m else ""
    except Exception:
        return ""


def _alive(url: str) -> bool:
    try:
        r = urllib.request.urlopen(url, timeout=8)
        return 200 <= r.status < 400
    except Exception:
        return False


def _running(container: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() == "true"
    except Exception:
        return False


def _notify(title: str, message: str) -> None:
    key = _internal_key()
    if not key:
        return
    try:
        data = json.dumps(
            {
                "type": "warning",
                "title": title,
                "message": message,
                "source": "media_streaming_watchdog",
                "priority": "high",
            }
        ).encode()
        req = urllib.request.Request(
            f"{HUB}/api/notifications",
            data=data,
            headers={"Content-Type": "application/json", "X-Internal-Key": key},
        )
        urllib.request.urlopen(req, timeout=6)
    except Exception:
        pass


def main() -> None:
    for e in ENGINES:
        if _alive(e["url"]):
            print(f"{e['name']}: ok")
            continue
        # Endpoint down. Restart ONLY if the container is running (i.e. HUNG),
        # so we never fight an intentional stop or a boot-in-progress.
        if _running(e["container"]):
            res = subprocess.run(
                ["docker", "restart", e["container"]],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if res.returncode == 0:
                print(f"{e['name']}: HUNG (container up, HTTP down) -> restarted {e['container']}")
                _notify(
                    f"Media watchdog — {e['name']} auto-restarted",
                    f"{e['name']} web server was not responding (container up but HTTP down) — "
                    f"auto-restarted {e['container']}.",
                )
            else:
                print(f"{e['name']}: restart FAILED: {res.stderr.strip()[:120]}")
                _notify(
                    f"Media watchdog — {e['name']} restart FAILED",
                    f"{e['name']} not responding and `docker restart {e['container']}` failed — manual check needed.",
                )
        else:
            print(f"{e['name']}: down and container not running")
            _notify(
                f"Media watchdog — {e['name']} down",
                f"{e['name']} not responding and container {e['container']} is not running — manual check needed.",
            )


if __name__ == "__main__":
    main()
