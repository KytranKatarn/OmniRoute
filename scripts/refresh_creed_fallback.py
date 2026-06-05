#!/usr/bin/env python3
"""Refresh the creed-ai.org governance fallback snapshot from the live C.R.E.E.D. API.

The creed-ai.org governance widget falls back to a SAME-ORIGIN
data/governance-fallback.json when the live API can't be reached cross-origin
(e.g. Chrome Private Network Access on a LAN, or an outage). That snapshot must
not drift, so this host cron regenerates it weekly from the live scores and
commits it to the creed-ai-site repo.

NOTE: pushing it LIVE still requires a Hostinger deploy (Claude session /
/deploy-website creed-ai.org) — there is no headless Hostinger deploy path. This
script keeps the SOURCE current + commits; the file ships on the next deploy.

Run: weekly via cron (see crontab). Fetches the creed container directly on the
hub (127.0.0.1:8086) — no DNS/proxy/PNA involved.
"""
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

API_URL = "http://127.0.0.1:8086/api/v1/scores"
REPO = "/mnt/standalone/websites/creed-ai.org"
OUT = f"{REPO}/data/governance-fallback.json"
TORONTO = ZoneInfo("America/Toronto")


def main() -> int:
    try:
        raw = urllib.request.urlopen(API_URL, timeout=20).read().decode("utf-8")
        live = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh_creed_fallback] live API fetch failed: {e}", file=sys.stderr)
        return 1

    # Validate the shape the widget expects.
    if not isinstance(live.get("overall"), (int, float)) or "by_category" not in live:
        print(f"[refresh_creed_fallback] unexpected API shape: {list(live.keys())}", file=sys.stderr)
        return 1

    snapshot = {
        "_comment": "Same-origin fallback for the governance widget when the live C.R.E.E.D. "
        "API is unreachable (Chrome PNA on a LAN, or an outage). Matches /api/v1/scores. "
        "Auto-refreshed weekly by scripts/refresh_creed_fallback.py.",
        "_snapshot_date": datetime.now(TORONTO).strftime("%Y-%m-%d"),
        "overall": live["overall"],
        "grade": live.get("grade"),
        "event_count": live.get("event_count"),
        "by_category": live.get("by_category", {}),
    }

    new_text = json.dumps(snapshot, indent=2) + "\n"
    try:
        with open(OUT) as f:
            if f.read() == new_text:
                print("[refresh_creed_fallback] snapshot unchanged; nothing to commit")
                return 0
    except FileNotFoundError:
        pass

    with open(OUT, "w") as f:
        f.write(new_text)

    # Commit just this file (best-effort; deploy is a separate Claude step).
    try:
        subprocess.run(["git", "-C", REPO, "add", "data/governance-fallback.json"], check=True)
        subprocess.run(
            ["git", "-C", REPO, "-c", "user.name=archie-cron",
             "-c", "user.email=noreply@anthropic.com", "commit", "-q", "-m",
             f"chore(governance): refresh fallback snapshot {snapshot['_snapshot_date']}"],
            check=True,
        )
        print(f"[refresh_creed_fallback] committed snapshot {snapshot['_snapshot_date']} "
              f"(overall {snapshot['overall']} {snapshot['grade']}). Deploy with /deploy-website creed-ai.org.")
    except subprocess.CalledProcessError as e:
        print(f"[refresh_creed_fallback] wrote file but git commit failed: {e}", file=sys.stderr)
        return 0  # file is updated regardless
    return 0


if __name__ == "__main__":
    sys.exit(main())
