"""Full Security Review — bucket-1 CODE layer (Security & Network).

These are the grounded, static-verifiable code cores of the scanner/defense/
automation pipeline. The end-to-end live proof (containers running, a real scan
landing in security_scan_results, fail2ban installed) is deliberately NOT claimed
here — it needs the restart + host access. What IS proven:

  #5675 scanner pipeline code:
    - findings parsers read result['output'] but _docker_exec returns 'stdout'
      -> every scan reported 0 findings.
    - scanner_routes indexed RealDictCursor rows by int position (row[0]) so
      campaign create/get/list + findings/running/summary all 500'd.
  auto-block: suggestion_type carries a ':<ip>' suffix so the exact-membership
      filter silently skipped every device_vulnerability suggestion.
  info-leak: fingerprint_routes/pcap_routes returned raw str(e) to the client.
  dead-code: a shadowed duplicate loadHoneypotEvents() in features.js.
  logging: the job-count line was off by one.
"""

import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "security_network")
_JSF = os.path.join(os.path.dirname(__file__), "..", "static", "js", "security-network-features.js")


def _src(p):
    return open(p).read()


# ---- #5675: scanner parser key + RealDictCursor sweep ----------------------
def test_scanner_parsers_read_stdout_not_output():
    s = _src(os.path.join(_MOD, "scanner_routes.py"))
    assert '.get("output"' not in s, "parser still reads the phantom 'output' key"
    assert '.get("stdout"' in s


def test_scanner_routes_no_realdict_int_indexing():
    s = _src(os.path.join(_MOD, "scanner_routes.py"))
    # the int-indexed cursor reads are gone
    assert "cur.fetchone()[0]" not in s
    assert '"id": row[0]' not in s
    assert '"id": r[0]' not in s
    assert "{r[0]: r[1]" not in s
    # named access is in place at representative sites
    assert 'campaign_id = cur.fetchone()["id"]' in s
    assert 'scan_id = cur.fetchone()["id"]' in s
    assert '"client_name": row["client_name"]' in s
    assert '{r["severity"]: r["count"]' in s
    assert 'list(row["array_agg"])' in s


# ---- auto-block prefix match -----------------------------------------------
def test_autoblock_matches_suggestion_type_prefix():
    s = _src(os.path.join(_MOD, "jobs.py"))
    assert 'stype.split(":")[0] in (' in s
    # the broken exact-membership form is gone
    assert "and stype in (" not in s


# ---- job-count log accuracy ------------------------------------------------
def test_job_count_log_is_22():
    s = _src(os.path.join(_MOD, "jobs.py"))
    assert "Registered 22 security/network jobs" in s
    assert "Registered 21 security/network jobs" not in s


# ---- info-leak hardening ---------------------------------------------------
def test_fingerprint_and_pcap_do_not_leak_exception_text():
    fp = _src(os.path.join(_MOD, "fingerprint_routes.py"))
    assert '"error": str(e)' not in fp
    pc = _src(os.path.join(_MOD, "pcap_routes.py"))
    assert '"error": str(e)' not in pc


# ---- dead shadowed JS function removed -------------------------------------
def test_single_loadhoneypotevents_definition():
    js = _src(_JSF)
    assert js.count("function loadHoneypotEvents") == 1
    # the dead shadow's unique body text is gone (the /threat-intel/dns-crossref
    # endpoint itself is legitimately used elsewhere, so don't assert on that)
    assert "Honeypot monitoring via DNS threat correlation" not in js
