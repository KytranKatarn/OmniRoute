"""Full Security Review — bucket-2 follow-ups (Security & Network):
un-gated code fixes that don't need a live drive.

  1. threat_intel_routes /iocs queried phantom columns feed_source/threat_type
     (real schema: feed_name/description) -> every call 500'd.
  2. device_presence_log had no CREATE TABLE migration (lived only in the live DB)
     -> fresh install silently breaks presence tracking.
  3. compliance evidence render interpolated rule_id/pack_id into innerHTML
     unescaped while the sibling fields were escaped.
  4. Quick Setup reported Proxy/SSL steps the backend never produces (NPM-era
     leftover -> permanent misleading ✗).
"""

import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "security_network")
# Was os.path.join(dirname(__file__), "..", "..", ...) = "/database/migrations" in the test
# container, where platform_v2 is mounted AS /app — the os.path spelling of #5994. The
# migration is on disk and mounted; only the path was wrong, so "migration 469 missing"
# named the wrong cause.
from tests.repo_root import repo_path  # noqa: E402

_MIG = str(repo_path("database", "migrations"))
_JSA = os.path.join(os.path.dirname(__file__), "..", "static", "js", "security-network-app.js")


def _src(p):
    return open(p).read()


# ---- 1. threat_intel /iocs: real columns only ------------------------------
def test_threat_intel_iocs_uses_real_columns():
    s = _src(os.path.join(_MOD, "threat_intel_routes.py"))
    # the phantom columns are gone from SQL and response mapping
    assert "feed_source = %s" not in s  # WHERE filter fixed
    assert "SELECT id, ioc_type, ioc_value, severity, feed_name, " in s
    assert '"threat_type": r["threat_type"]' not in s
    assert 'r["feed_source"]' not in s  # no read of a column that doesn't exist
    # real columns are read
    assert 'r["feed_name"]' in s
    assert 'r["description"]' in s


# ---- 2. device_presence_log migration exists + idempotent ------------------
def test_device_presence_log_migration_present():
    path = os.path.join(_MIG, "469_device_presence_log.sql")
    assert os.path.exists(path), "migration 469 missing"
    s = _src(path)
    assert "CREATE TABLE IF NOT EXISTS device_presence_log" in s
    # columns match the live schema
    for col in ("device_ip", "device_mac", "event_type", "detected_at"):
        assert col in s, f"migration missing column {col}"
    # indexes are idempotent too
    assert s.count("CREATE INDEX IF NOT EXISTS") == 2


# ---- 3. compliance evidence render escapes rule_id/pack_id -----------------
def test_compliance_evidence_escapes_rule_and_pack():
    s = _src(_JSA)
    assert "_compEsc(f.rule_id)" in s
    assert "_compEsc((f.pack_id || '').replace('-stig', ''))" in s
    # the bare unescaped interpolations are gone
    assert "'</span>'\n" not in s or "+ f.rule_id +" not in s
    assert "+ f.rule_id +" not in s
    assert "+ (f.pack_id || '').replace('-stig', '') +" not in s


# ---- 4. Quick Setup no longer reports phantom Proxy/SSL steps ---------------
def test_quicksetup_drops_phantom_proxy_ssl():
    s = _src(_JSA)
    assert "d.steps.proxy" not in s
    assert "d.steps.ssl" not in s
    assert "TLS auto-provisioned by the ingress" in s
