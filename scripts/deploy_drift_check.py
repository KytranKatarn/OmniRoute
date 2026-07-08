#!/usr/bin/env python3
"""
Deploy-drift monitor (KB mistake #279350).

For each image-baked product, fetch its /version baked ``git_sha`` and compare it
against the current ``origin/main`` HEAD of the archie-platform repo. A running
container whose image was built from a stale commit OR an orphan feature branch
reports a SHA that isn't main -> flag it. This makes the exact failure from
project #385 (five per-branch deploys left the container reflecting only the
last one) VISIBLE instead of silent, and it also catches the recurring
hub-git != live-VPS-deploy drift on the watch products (KB #275549).

Alerts route through A.R.C.H.I.E. (POST /api/internal/notify, Bearer
INTERNAL_API_KEY) so drift shows up as a notification / Telegram, not just stdout.

Fail-open: an unreachable or unstamped ("unknown") product is NOT counted as
drift — we only alarm on a concrete, mismatched SHA.

    python3 scripts/deploy_drift_check.py            # report only, exit 1 if drift
    python3 scripts/deploy_drift_check.py --notify   # + A.R.C.H.I.E. alert on drift

Endpoints are env-overridable (the hub host->own-published-port hairpin is
unreliable since userland-proxy=false — override to bridge/mesh IPs as needed):
    DRIFT_MEDIA_HUB_URL   (default http://192.168.1.200:8105/version)
    ARCHIE_HUB_URL        (default http://100.64.0.4:3000  — mesh, for notify)
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

REPO = os.getenv("ARCHIE_REPO", "/mnt/archie_brain")

# product -> /version URL. Extend as watch products adopt the /version stamp.
PRODUCTS = {
    "media_hub": os.getenv("DRIFT_MEDIA_HUB_URL", "http://192.168.1.200:8105/version"),
}


def _main_head() -> str:
    subprocess.run(["git", "-C", REPO, "fetch", "-q", "origin", "main"], check=False)
    return subprocess.check_output(["git", "-C", REPO, "rev-parse", "origin/main"]).decode().strip()


def _baked_sha(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=6) as r:  # noqa: S310 — trusted LAN endpoint
            return (json.loads(r.read().decode()) or {}).get("git_sha", "unknown")
    except Exception as e:  # noqa: BLE001 — unreachable is fail-open, never drift
        return f"unreachable:{e}"


def _notify(title: str, message: str) -> None:
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        print("  (no INTERNAL_API_KEY in env — skipping A.R.C.H.I.E. alert)")
        return
    hub = (os.getenv("ARCHIE_HUB_URL") or "http://100.64.0.4:3000").rstrip("/")
    body = json.dumps(
        {"title": title, "message": message, "priority": "high",
         "source": "deploy_drift_monitor", "telegram": True}
    ).encode()
    req = urllib.request.Request(
        f"{hub}/api/internal/notify", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=8)  # noqa: S310
        print("  → A.R.C.H.I.E. alerted")
    except Exception as e:  # noqa: BLE001
        print("  alert failed:", e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="alert A.R.C.H.I.E. on drift")
    args = ap.parse_args()

    head = _main_head()
    print(f"origin/main HEAD = {head[:12]}")
    drift = []
    for name, url in PRODUCTS.items():
        baked = _baked_sha(url)
        short = baked[:12]
        # A stamp may carry a "+dirty" suffix; compare the bare 40-char prefix.
        bare = baked.split("+", 1)[0]
        if bare == head:
            print(f"  ✓ {name}: in sync ({short})")
        elif baked == "unknown" or baked.startswith("unreachable"):
            print(f"  ? {name}: {short} — no stamp yet / unreachable (fail-open, not drift)")
        else:
            print(f"  ✗ {name}: DRIFT — running {short}, main is {head[:12]}")
            drift.append((name, baked))

    if drift and args.notify:
        lines = "\n".join(f"• {n}: running {s[:12]}, main {head[:12]}" for n, s in drift)
        _notify("Deploy drift detected",
                f"{len(drift)} product(s) running a non-main image:\n{lines}\nRebuild from main.")
    sys.exit(1 if drift else 0)


if __name__ == "__main__":
    main()
