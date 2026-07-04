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

SCORES_URL = "http://127.0.0.1:8086/api/v1/scores"
ORGS_URL = "http://127.0.0.1:8086/api/v1/orgs"
REPO = "/mnt/standalone/websites/creed-ai.org"
GOV_OUT = f"{REPO}/data/governance-fallback.json"
DIR_OUT = f"{REPO}/data/directory-fallback.json"
TORONTO = ZoneInfo("America/Toronto")


def _fetch_json(url: str):
    raw = urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
    return json.loads(raw)


def _write_if_changed(path: str, text: str) -> bool:
    """Write text to path only when it differs; return True if the file changed."""
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    with open(path, "w") as f:
        f.write(text)
    return True


def main() -> int:
    today = datetime.now(TORONTO).strftime("%Y-%m-%d")
    changed = []

    # --- 1. Governance scores snapshot (institute, 6-pillar) ---
    try:
        live = _fetch_json(SCORES_URL)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh_creed_fallback] live scores fetch failed: {e}", file=sys.stderr)
        return 1
    if not isinstance(live.get("overall"), (int, float)) or "by_category" not in live:
        print(f"[refresh_creed_fallback] unexpected scores shape: {list(live.keys())}", file=sys.stderr)
        return 1
    gov_snapshot = {
        "_comment": "Same-origin fallback for the governance widget when the live C.R.E.E.D. "
        "API is unreachable (Chrome PNA on a LAN, or an outage). Matches /api/v1/scores. "
        "Auto-refreshed weekly by scripts/refresh_creed_fallback.py.",
        "_snapshot_date": today,
        "overall": live["overall"],
        "grade": live.get("grade"),
        "event_count": live.get("event_count"),
        "by_category": live.get("by_category", {}),
    }
    if _write_if_changed(GOV_OUT, json.dumps(gov_snapshot, indent=2) + "\n"):
        changed.append("data/governance-fallback.json")

    # --- 2. Public transparency directory snapshot (multi-tenant) ---
    # Best-effort: a directory fetch failure must not block the scores snapshot.
    try:
        orgs = _fetch_json(ORGS_URL)
        org_list = orgs.get("orgs") if isinstance(orgs, dict) else orgs
        if not isinstance(org_list, list):
            raise ValueError(f"unexpected orgs shape: {type(org_list).__name__}")
        dir_snapshot = {
            "_comment": "Same-origin fallback for the transparency directory when the live "
            "C.R.E.E.D. API is unreachable (Chrome PNA on a LAN, or an outage). Matches "
            "/api/v1/orgs. Auto-refreshed weekly by scripts/refresh_creed_fallback.py.",
            "_snapshot_date": today,
            "count": len(org_list),
            "orgs": org_list,
        }
        if _write_if_changed(DIR_OUT, json.dumps(dir_snapshot, indent=2) + "\n"):
            changed.append("data/directory-fallback.json")
    except Exception as e:  # noqa: BLE001
        print(f"[refresh_creed_fallback] directory snapshot skipped: {e}", file=sys.stderr)

    if not changed:
        print("[refresh_creed_fallback] snapshots unchanged; nothing to commit")
        return 0

    # Commit just the snapshot files (best-effort; deploy is a separate Claude step).
    try:
        subprocess.run(["git", "-C", REPO, "add", *changed], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                REPO,
                "-c",
                "user.name=archie-cron",
                "-c",
                "user.email=noreply@anthropic.com",
                "commit",
                "-q",
                "-m",
                f"chore(governance): refresh fallback snapshots {today}",
            ],
            check=True,
        )
        print(
            f"[refresh_creed_fallback] committed {', '.join(changed)} ({today}). "
            f"Deploy with /deploy-website creed-ai.org."
        )
    except subprocess.CalledProcessError as e:
        print(f"[refresh_creed_fallback] wrote files but git commit failed: {e}", file=sys.stderr)
        return 0  # files are updated regardless
    return 0


if __name__ == "__main__":
    sys.exit(main())
