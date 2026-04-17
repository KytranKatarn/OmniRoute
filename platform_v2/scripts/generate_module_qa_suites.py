"""Generate baseline P.R.O.B.E. YAML suites for every registered Flask blueprint.

Task #1729 — expand QA coverage across all platform modules. Rather than
hand-writing 46 suites, this script introspects ``app.url_map`` and emits
a YAML per blueprint containing a ``page_load`` or ``api`` test for every
GET route that has no path parameters.

The generated suites are deliberately thin — they check that every static
route returns an acceptable status (200 / 302 / 401) and nothing more.
Higher-fidelity suites for specific modules still live in
``platform_v2/qa_suites/*.yaml`` as curated fixtures.

Usage (inside the archie_platform container)::

    python3 /app/scripts/generate_module_qa_suites.py \\
        --out /app/qa_suites/auto \\
        --base-url http://192.168.1.200:3000

By default the script reads ``ARCHIE_TEST_USERNAME``/``ARCHIE_TEST_PASSWORD``
from the environment and emits them as ``${VAR}`` references in the YAML
so qa_spec_runner will resolve them at run time.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

# Allow running directly inside archie_platform
sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Blueprint → human-readable suite name / category
# ---------------------------------------------------------------------------

BLUEPRINT_META: Dict[str, Dict[str, str]] = {
    "account_center": {"name": "Admin Ops — Account Center (auto)", "category": "admin"},
    "agent_academy": {"name": "AI Command — Agent Academy (auto)", "category": "ai"},
    "api_gateway": {"name": "Infra — API Gateway (auto)", "category": "infra"},
    "archie_pool": {"name": "Crypto — Archie Pool (auto)", "category": "crypto"},
    "backup_manager": {"name": "Admin Ops — Backup Manager (auto)", "category": "admin"},
    "billing": {"name": "SaaS — Billing (auto)", "category": "saas"},
    "compliance_badges": {"name": "Compliance — Public Badges (auto)", "category": "public"},
    "consciousness": {"name": "AI Command — Consciousness (auto)", "category": "ai"},
    "creed_admin": {"name": "C.R.E.E.D. — Admin (auto)", "category": "admin"},
    "creed_public": {"name": "C.R.E.E.D. — Public (auto)", "category": "public"},
    "cursor": {"name": "Tools — Cursor (auto)", "category": "tools"},
    "department_hq": {"name": "AI Command — Department HQ (auto)", "category": "ai"},
    "doc": {"name": "Applications — DOC (auto)", "category": "applications"},
    "family_tree": {"name": "SaaS — Family Tree (auto)", "category": "saas"},
    "fitness": {"name": "Applications — Fitness (auto)", "category": "applications"},
    "game_studio": {"name": "Creative Studios — Game Studio (auto)", "category": "creative"},
    "google_work_suite": {"name": "SaaS — Google Work Suite (auto)", "category": "saas"},
    "media_hub": {"name": "Media Home — Media Hub (auto)", "category": "media"},
    "media_studio": {"name": "Creative Studios — Media Studio (auto)", "category": "creative"},
    "oauth": {"name": "Infra — OAuth Clients (auto)", "category": "infra"},
    "oauth_provider": {"name": "Infra — OAuth Provider (auto)", "category": "infra"},
    "oauth_userinfo": {"name": "Infra — OAuth UserInfo (auto)", "category": "infra"},
    "pool_management": {"name": "Crypto — Pool Management (auto)", "category": "crypto"},
    "public_api": {"name": "Infra — Public API (auto)", "category": "infra"},
    "repair_bay": {"name": "AI Command — Repair Bay (auto)", "category": "ai"},
    "saas_manager": {"name": "SaaS — SaaS Manager (auto)", "category": "saas"},
    "sandbox": {"name": "Dev — Sandbox (auto)", "category": "dev"},
    "security_network": {"name": "Admin Ops — Security & Network (auto)", "category": "admin"},
    "standalone_api": {"name": "Infra — Standalone API (auto)", "category": "infra"},
    "therapy": {"name": "Applications — Therapy (auto)", "category": "applications"},
    "triage": {"name": "AI Command — Triage (auto)", "category": "ai"},
    "user_profile": {"name": "Admin Ops — User Profile (auto)", "category": "admin"},
}

# Blueprints we explicitly skip (covered by other suites, or not meaningful
# as HTTP endpoints).
SKIP_BLUEPRINTS = {"root", "static", "debugtoolbar", "_debug_toolbar"}


# ---------------------------------------------------------------------------
# Route extraction
# ---------------------------------------------------------------------------


def _collect_rules_by_blueprint():
    """Return dict[blueprint_name] -> list[(method, path)] of GET-static routes."""
    from app import app  # noqa: WPS433

    out = defaultdict(list)
    for rule in app.url_map.iter_rules():
        endpoint = rule.endpoint or ""
        if "." not in endpoint:
            continue
        bp, _ = endpoint.split(".", 1)
        if bp in SKIP_BLUEPRINTS:
            continue
        methods = rule.methods or set()
        if "GET" not in methods:
            continue
        # Skip routes with path parameters — we don't know what id/slug to pass
        if "<" in rule.rule or ">" in rule.rule:
            continue
        # Skip static-file routes
        if rule.rule.startswith("/static/"):
            continue
        out[bp].append(rule.rule)
    # Sort each list for deterministic output
    return {bp: sorted(set(paths)) for bp, paths in out.items()}


def _slug(path: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return s or "root"


def _test_type_for(path: str) -> str:
    """API routes under /api/ get ``type: api``; everything else is ``page_load``."""
    return "api" if "/api/" in path or path.endswith("/api") else "page_load"


# ---------------------------------------------------------------------------
# YAML emission
# ---------------------------------------------------------------------------


def _yaml_escape(value: str) -> str:
    """Minimal YAML string escaping for path/name values."""
    if any(ch in value for ch in ":#{}[]&*!|>'%\"@\\`"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _emit_suite_yaml(name: str, base_url: str, tests: List[dict]) -> str:
    lines: List[str] = [
        "# Auto-generated P.R.O.B.E. suite — Task #1729.",
        "# Re-run platform_v2/scripts/generate_module_qa_suites.py to refresh.",
        "suite:",
        f"  name: {_yaml_escape(name)}",
        f"  description: {_yaml_escape('Auto-generated baseline coverage — ' + str(len(tests)) + ' GET routes.')}",
        f"  base_url: {_yaml_escape(base_url)}",
        "  auth:",
        '    username: "${ARCHIE_TEST_USERNAME}"',
        '    password: "${ARCHIE_TEST_PASSWORD}"',
        "",
        "tests:",
    ]
    for t in tests:
        lines.append(f"  - name: {_yaml_escape(t['name'])}")
        lines.append(f"    type: {t['type']}")
        if t["type"] == "api":
            lines.append("    method: GET")
        lines.append(f"    path: {_yaml_escape(t['path'])}")
        lines.append("    expect:")
        lines.append("      status: [200, 301, 302, 304, 401]")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/app/qa_suites/auto", help="Output directory")
    parser.add_argument(
        "--base-url",
        default=os.getenv("PROBE_BASE_URL", "http://192.168.1.200:3000"),
    )
    parser.add_argument(
        "--max-per-suite",
        type=int,
        default=40,
        help="Cap tests per suite (top-N largest blueprints get trimmed)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rules_by_bp = _collect_rules_by_blueprint()
    print(f"Discovered {len(rules_by_bp)} blueprints with GET-static routes")

    manifest = []
    for bp, paths in sorted(rules_by_bp.items()):
        if not paths:
            continue
        meta = BLUEPRINT_META.get(bp, {"name": f"Auto — {bp}", "category": "misc"})
        trimmed = paths[: args.max_per_suite]
        skipped = len(paths) - len(trimmed)
        tests = [
            {
                "name": f"{bp}-{_slug(p)}",
                "type": _test_type_for(p),
                "path": p,
            }
            for p in trimmed
        ]
        yaml_text = _emit_suite_yaml(meta["name"], args.base_url, tests)
        out_file = out_dir / f"{bp}.yaml"
        out_file.write_text(yaml_text)
        manifest.append(
            {
                "blueprint": bp,
                "file": out_file.name,
                "tests": len(tests),
                "skipped": skipped,
                "name": meta["name"],
            }
        )
        print(
            f"  {bp:30s}  {len(tests):>4} tests{'  (+' + str(skipped) + ' skipped)' if skipped else ''}  → {out_file.name}"
        )

    print(f"\nWrote {len(manifest)} suite file(s) to {out_dir}")
    return manifest


if __name__ == "__main__":
    main()
