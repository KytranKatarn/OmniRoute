"""Briefing health check (P.R.O.B.E. QA).

Runs every per-agent chat briefing (`tools/archie_chat/*_briefing.py`) and
flags any that return a swallowed error block instead of live module state.
This is the schema-drift detector for the briefing class of bug: each briefing
wraps its queries in try/except and appends "[briefing data unavailable: ...]"
on a SQL error, so a drifted column/table silently feeds the agent nothing —
no crash, no log alarm. See mistake_learned #269358 (PRs #1301/#1302/#1303,
where 6 of 19 briefings were found broken this way).

Single source of truth for both the scheduled job (`probe_briefing_health`)
and on-demand invocation.
"""

import importlib
import re

# Every per-agent chat briefing: module key -> tools/archie_chat/<key>_briefing.py
# with a _build_<key>_briefing() builder. Keep in sync with the briefing files.
BRIEFINGS = [
    "account_center",
    "agent_academy",
    "consciousness",
    "department_hq",
    "doc",
    "email_hq",
    "faith",
    "family_tree",
    "fitness",
    "google_work_suite",
    "media_hub",
    "media_studio",
    "pool",
    "repair_bay",
    "security_network",
    "therapy",
    "user_profile",
    "warden",
    "wtf_hub",
]

# A briefing's outer try/except appends "[briefing data unavailable: <exc>]"
# when a whole briefing breaks; raw "does not exist" catches schema errors that
# slip through. Inner per-stat graceful fallbacks (e.g. "no results yet") are
# intentionally NOT flagged — only full-briefing breakage.
_ERR = re.compile(r"\[briefing data unavailable|does not exist|undefinedcolumn", re.I)


def check_briefing_health() -> dict:
    """Run all briefings; return a result dict (mirrors dep_drift_service shape)."""
    failed = []
    ok = 0
    for key in BRIEFINGS:
        try:
            mod = importlib.import_module(f"tools.archie_chat.{key}_briefing")
            out = getattr(mod, f"_build_{key}_briefing")() or ""
            hit = _ERR.search(out)
            if hit:
                failed.append({"module": key, "error": hit.group(0)[:140]})
            else:
                ok += 1
        except Exception as e:  # noqa: BLE001 — health check must never raise
            failed.append({"module": key, "error": f"{type(e).__name__}: {str(e)[:120]}"})

    total = len(BRIEFINGS)
    n_fail = len(failed)
    severity = "ok" if n_fail == 0 else ("error" if n_fail >= 3 else "warning")
    return {
        "severity": severity,
        "total": total,
        "ok": ok,
        "failed": failed,
        "anomaly_count": n_fail,
        "summary_metrics": {"ok": ok, "failed": n_fail, "total": total},
        "reasons": [f"{f['module']}: {f['error']}" for f in failed],
    }


def format_alert_message(result: dict) -> str:
    if not result["failed"]:
        return f"All {result['total']} agent chat briefings healthy."
    lines = [
        f"⚠️ {len(result['failed'])}/{result['total']} agent chat briefings broken "
        "(schema drift — agents getting '[briefing data unavailable]' not live state):"
    ]
    for f in result["failed"]:
        lines.append(f"  • {f['module']}: {f['error']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json

    print(json.dumps(check_briefing_health(), indent=2))
