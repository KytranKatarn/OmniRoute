"""
Asserts no code outside telegram_service.py calls the Telegram API directly.

telegram_service.py is the ONE authorized internal sender — it is explicitly
excluded from the api.telegram.org check. Everything else must route through
send_agent() / send_system() / send_forge() / send_with_buttons() which all
delegate to director_report_service.submit_via_inbox() (or the privileged
send() path for A.R.C.H.I.E. itself).

Run: pytest tests/test_telegram_isolation.py -v
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCAN_DIRS = ["platform_v2", "ai_bridge"]

# The one authorized internal Telegram sender — its own direct API call is
# intentional and must not be flagged.
AUTHORIZED_SENDERS = {
    "platform_v2/services/telegram_service.py",
}


def _grep(pattern: str) -> list[str]:
    results = []
    for d in SCAN_DIRS:
        target = REPO_ROOT / d
        if not target.exists():
            continue
        proc = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, str(target)],
            capture_output=True,
            text=True,
        )
        if proc.stdout.strip():
            results.extend(proc.stdout.strip().splitlines())
    return results


def _is_authorized(line: str) -> bool:
    """Return True if the grep hit is in an authorized sender file."""
    for authorized_path in AUTHORIZED_SENDERS:
        if authorized_path in line:
            return True
    return False


def test_no_direct_telegram_api():
    """No code outside telegram_service.py should call api.telegram.org directly."""
    all_hits = _grep("api.telegram.org")
    violations = [line for line in all_hits if not _is_authorized(line)]
    assert violations == [], (
        "Direct Telegram API calls found outside the authorized sender.\n"
        "Use telegram_service.send_agent() / send_system() / send_with_buttons()\n"
        "or director_report_service.submit_via_inbox() instead.\n\n"
        + "\n".join(violations)
    )


def test_no_raw_bot_token_requests():
    """TELEGRAM_BOT_TOKEN should only appear in os.getenv() / getenv() declarations.

    Excluded from the check:
    - telegram_service.py itself (the authorized Telegram sender)
    - Lines that are comments, docstrings, or logger/print calls referencing the
      token name as a string (not as an active variable dereference)
    """
    all_refs = _grep("TELEGRAM_BOT_TOKEN")
    violations = [
        line
        for line in all_refs
        if not _is_authorized(line)           # allow telegram_service.py
        and "os.getenv" not in line
        and "getenv" not in line
        and not line.strip().startswith("#")  # skip comments
        and "logger." not in line             # skip log strings mentioning the var name
        and "print(" not in line              # skip debug prints
    ]
    assert violations == [], (
        "Active TELEGRAM_BOT_TOKEN usage found outside archie-comms/.\n"
        "Migrate to telegram_service send helpers or submit_via_inbox().\n\n"
        + "\n".join(violations)
    )
