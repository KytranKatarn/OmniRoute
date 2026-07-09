#!/usr/bin/env python3
"""
Deploy-drift monitor (KB mistake #279350).

For each image-baked product, fetch its /version baked ``git_sha`` and compare it
against the latest commit that TOUCHED THAT PRODUCT'S SOURCE PATH on its repo's
main branch (resolved via the GitHub API). A running container whose image was
built from a stale commit OR an orphan feature branch reports a SHA that isn't the
product's current source head -> flag it. This makes the exact failure from
project #385 (five per-branch deploys left the container reflecting only the last
one) VISIBLE instead of silent, and also catches the recurring hub-git !=
live-VPS-deploy drift on the watch products (KB #275549).

Why path-aware, not global HEAD: products are rebuilt only when THEIR code changes,
so a product legitimately lags the repo's global HEAD between its own deploys.
Comparing to global HEAD would flag EVERY product as "drift" after ANY unrelated
merge — a cry-wolf monitor. Comparing to the latest commit touching the product's
PATH means a product is "drift" only when its own source has un-deployed changes.

Expected-SHA is resolved via the GitHub API (Bearer GITHUB_TOKEN / FORGE_REVIEW_TOKEN),
NOT local git — the scheduler container has no git credentials for a fetch, and the
API is always fresh. No local repo/clone is required.

Alerts route through A.R.C.H.I.E. (POST /api/internal/notify, Bearer
INTERNAL_API_KEY) so drift shows up as a notification / Telegram, not just stdout.

Fail-open: an unreachable/unstamped product, OR an unresolvable expected-SHA
(product source in a not-yet-wired repo, or a GitHub API hiccup), is NOT counted as
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
import sys
import urllib.parse
import urllib.request

# Where each product's SOURCE lives. media_hub is a subtree of archie-platform;
# KBS/KSO and the watch products live in their own trees/repos and get their
# (repo, path) wired when they adopt the /version stamp (task #4749 part 1) — until
# then repo=None means "expected-SHA unresolvable → fail-open (never drift)".
_ARCHIE = "KytranKatarn/archie-platform"

# name -> {url, repo, path}. url is env-overridable (userland-proxy=false host-hairpin
# caveat, KB #275737): from a host cron the hub can't reach its OWN published ports via
# 192.168.1.200 — override DRIFT_*_URL to a container/bridge address; Citadel/boston-2
# products are reached over the Headscale mesh (100.64.0.10). repo=None ⇒ fail-open.
PRODUCTS = {
    # Hub — archie-platform subtree
    "media_hub": {
        "url": os.getenv("DRIFT_MEDIA_HUB_URL", "http://192.168.1.200:8105/version"),
        "repo": _ARCHIE,
        "path": "standalone/media_hub",
    },
    # Hub — separate trees (repo/path wired at part 1)
    "kbs": {"url": os.getenv("DRIFT_KBS_URL", "http://192.168.1.200:8091/version"), "repo": None, "path": None},
    "kso": {"url": os.getenv("DRIFT_KSO_URL", "http://192.168.1.200:8085/version"), "repo": None, "path": None},
    # Citadel / boston-2 (mesh 100.64.0.10) — separate repos (repo/path wired at part 1)
    "wtf_consumer": {"url": os.getenv("DRIFT_WTF_URL", "http://100.64.0.10:8103/version"), "repo": None, "path": None},
    "gov_watch": {"url": os.getenv("DRIFT_GOV_URL", "http://100.64.0.10:8102/version"), "repo": None, "path": None},
    "market_watch": {
        "url": os.getenv("DRIFT_MARKET_URL", "http://100.64.0.10:8101/version"),
        "repo": None,
        "path": None,
    },
    "legal_watch": {"url": os.getenv("DRIFT_LEGAL_URL", "http://100.64.0.10:8100/version"), "repo": None, "path": None},
    "civic_watch": {"url": os.getenv("DRIFT_CIVIC_URL", "http://100.64.0.10:8099/version"), "repo": None, "path": None},
}

_GH_BRANCH = os.getenv("DRIFT_MAIN_BRANCH", "main")


def _gh_token() -> str:
    return os.getenv("GITHUB_TOKEN") or os.getenv("FORGE_REVIEW_TOKEN") or ""


def _expected_sha(repo, path) -> str:
    """Latest commit SHA on ``repo``'s main branch that touched ``path`` (or the branch
    head when path is falsy), via the GitHub API. Returns None on any failure / when repo
    is None — the caller then fails-open (never drift). No local git required."""
    if not repo:
        return None
    q = {"sha": _GH_BRANCH, "per_page": "1"}
    if path:
        q["path"] = path
    url = f"https://api.github.com/repos/{repo}/commits?" + urllib.parse.urlencode(q)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "archie-deploy-drift"}
    token = _gh_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 — GitHub API
            data = json.loads(r.read().decode())
            return data[0]["sha"] if data else None
    except Exception:  # noqa: BLE001 — unresolved expected is fail-open, never drift
        return None


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
        {"title": title, "message": message, "priority": "high", "source": "deploy_drift_monitor", "telegram": True}
    ).encode()
    req = urllib.request.Request(
        f"{hub}/api/internal/notify",
        data=body,
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

    drift = []
    for name, meta in PRODUCTS.items():
        expected = _expected_sha(meta.get("repo"), meta.get("path"))
        baked = _baked_sha(meta["url"])
        bare = baked.split("+", 1)[0]  # a stamp may carry a "+dirty" suffix
        short = baked[:12]
        if not expected:
            print(f"  ? {name}: {short} — source repo not wired yet (fail-open, not drift)")
        elif baked == "unknown" or baked.startswith("unreachable"):
            print(f"  ? {name}: {short} — no stamp yet / unreachable (fail-open, not drift)")
        elif bare == expected:
            print(f"  ✓ {name}: in sync ({short})")
        else:
            print(f"  ✗ {name}: DRIFT — running {short}, source head is {expected[:12]}")
            drift.append((name, baked, expected))

    if drift and args.notify:
        lines = "\n".join(f"• {n}: running {s[:12]}, source head {e[:12]}" for n, s, e in drift)
        _notify(
            "Deploy drift detected",
            f"{len(drift)} product(s) running an image behind their source:\n{lines}\nRebuild from main.",
        )
    sys.exit(1 if drift else 0)


if __name__ == "__main__":
    main()
