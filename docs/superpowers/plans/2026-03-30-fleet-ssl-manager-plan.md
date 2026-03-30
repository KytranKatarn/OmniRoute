# Fleet SSL Manager — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically renew a `*.kytranempowerment.com` wildcard SSL cert via DNS-01 challenge using Hostinger's API, then serve it to fleet nodes via a pull endpoint.

**Architecture:** Pure Python ACME client (`cert_manager.py`) handles DNS-01 flow via Hostinger DNS API. Agent loop job runs daily, renews if <30 days to expiry. Hub serves cert via fleet API. KSO nodes pull cert on startup + every 12h.

**Tech Stack:** Python `acme` + `cryptography` + `josepy` libraries, Hostinger DNS REST API, Flask endpoints, APScheduler

**Spec:** `docs/superpowers/specs/2026-03-30-fleet-ssl-manager-design.md`

---

## File Structure

### New Files

```
ai_bridge/cert_manager.py                                          — ACME DNS-01 flow + Hostinger DNS + cert storage
kytran-server-manager/kytran_server_manager/services/cert_service.py — KSO cert pull + sync
```

### Modified Files

```
ai_bridge/agent_loop.py                     — register job #61 (_renew_fleet_ssl)
platform_v2/tools/starbase/fleet_routes.py  — add cert serving endpoints
docker-compose.yml                          — mount cert volume
```

---

## Task 1: Cert Manager Module — Core Functions

**Files:**
- Create: `ai_bridge/cert_manager.py`

- [ ] **Step 1: Create cert_manager.py with cert inspection + storage helpers**

```python
"""Fleet SSL Manager — wildcard cert renewal via ACME DNS-01 + Hostinger DNS API.

Handles the full lifecycle:
  1. check_cert_expiry() — days until cert expires
  2. renew_wildcard_cert() — ACME DNS-01 flow
  3. get_cert_info() — metadata for API serving
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)

CERT_BASE_DIR = os.environ.get("FLEET_CERT_DIR", "/opt/archie-fleet/certs")
WILDCARD_DIR = os.path.join(CERT_BASE_DIR, "wildcard")
ACCOUNT_KEY_PATH = os.path.join(CERT_BASE_DIR, "account.key")
ACCOUNT_URI_PATH = os.path.join(CERT_BASE_DIR, "account.uri")

HOSTINGER_API_BASE = "https://api.hostinger.com"
HOSTINGER_API_TOKEN = os.environ.get(
    "HOSTINGER_API_KEY",
    os.environ.get("HOSTINGER_API_TOKEN", ""),
)

# Use staging for testing, production for real certs
ACME_DIRECTORY = os.environ.get(
    "ACME_DIRECTORY",
    "https://acme-v02.api.letsencrypt.org/directory",
)
ACME_STAGING_DIRECTORY = "https://acme-staging-v02.api.letsencrypt.org/directory"


def check_cert_expiry(cert_path=None):
    """Return days until cert expires. -1 if cert doesn't exist."""
    if cert_path is None:
        cert_path = os.path.join(WILDCARD_DIR, "fullchain.pem")
    if not os.path.exists(cert_path):
        return -1
    try:
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        expires = cert.not_valid_after_utc
        now = datetime.now(timezone.utc)
        return (expires - now).days
    except Exception as e:
        logger.error(f"[SSL] Failed to read cert: {e}")
        return -1


def get_cert_info(cert_dir=None):
    """Return cert metadata: expires_at, sha256, domain, issuer."""
    if cert_dir is None:
        cert_dir = WILDCARD_DIR
    cert_path = os.path.join(cert_dir, "fullchain.pem")
    key_path = os.path.join(cert_dir, "privkey.pem")

    if not os.path.exists(cert_path):
        return None

    try:
        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        cert = x509.load_pem_x509_certificate(cert_pem)
        cert_hash = hashlib.sha256(cert_pem).hexdigest()

        # Extract SAN domains
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            domains = san.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            domains = []

        return {
            "expires_at": cert.not_valid_after_utc.isoformat(),
            "sha256": cert_hash,
            "domains": domains,
            "issuer": cert.issuer.rfc4514_string(),
            "has_key": os.path.exists(key_path),
        }
    except Exception as e:
        logger.error(f"[SSL] Failed to get cert info: {e}")
        return None


def _ensure_dirs():
    """Create cert directories if they don't exist."""
    os.makedirs(WILDCARD_DIR, exist_ok=True)


def _get_or_create_account_key():
    """Load or generate RSA 2048 account key for ACME."""
    _ensure_dirs()
    if os.path.exists(ACCOUNT_KEY_PATH):
        with open(ACCOUNT_KEY_PATH, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(ACCOUNT_KEY_PATH, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    os.chmod(ACCOUNT_KEY_PATH, 0o600)
    logger.info("[SSL] Generated new ACME account key")
    return key


# ── Hostinger DNS API ────────────────────────────────────────────


def _hostinger_headers():
    """Auth headers for Hostinger API."""
    return {
        "Authorization": f"Bearer {HOSTINGER_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _hostinger_get_dns_records(domain):
    """Get all DNS records for a domain from Hostinger."""
    resp = requests.get(
        f"{HOSTINGER_API_BASE}/api/dns/v1/zones/{domain}/records",
        headers=_hostinger_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _hostinger_create_txt_record(domain, name, value):
    """Create a TXT record via Hostinger DNS API.

    Hostinger's API uses PUT to update all records of a type.
    We need to GET existing records, add ours, then PUT back.
    """
    existing = _hostinger_get_dns_records(domain)

    # Build updated record set — keep all existing, add our TXT
    records = existing if isinstance(existing, list) else []

    # Add our ACME challenge TXT
    records.append({
        "type": "TXT",
        "name": name,
        "content": value,
        "ttl": 300,
    })

    resp = requests.put(
        f"{HOSTINGER_API_BASE}/api/dns/v1/zones/{domain}/records",
        headers=_hostinger_headers(),
        json=records,
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"[SSL] Created TXT record: {name}.{domain} = {value[:20]}...")
    return True


def _hostinger_delete_txt_record(domain, name, value):
    """Remove a specific TXT record via Hostinger DNS API."""
    existing = _hostinger_get_dns_records(domain)
    records = existing if isinstance(existing, list) else []

    # Filter out our challenge record
    filtered = [
        r for r in records
        if not (r.get("type") == "TXT" and r.get("name") == name and r.get("content") == value)
    ]

    resp = requests.put(
        f"{HOSTINGER_API_BASE}/api/dns/v1/zones/{domain}/records",
        headers=_hostinger_headers(),
        json=filtered,
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"[SSL] Removed TXT record: {name}.{domain}")
    return True


def _wait_for_dns_propagation(fqdn, expected_value, max_wait=120):
    """Poll DNS until TXT record is visible. Returns True if found."""
    import subprocess

    for attempt in range(max_wait // 10):
        try:
            result = subprocess.run(
                ["dig", "+short", "TXT", fqdn, "@8.8.8.8"],
                capture_output=True, text=True, timeout=10,
            )
            if expected_value in result.stdout.replace('"', ''):
                logger.info(f"[SSL] DNS propagated after {(attempt + 1) * 10}s")
                return True
        except Exception:
            pass
        time.sleep(10)

    logger.warning(f"[SSL] DNS propagation timeout after {max_wait}s")
    return False


# ── ACME DNS-01 Flow ─────────────────────────────────────────────


def renew_wildcard_cert(domain="kytranempowerment.com", cert_dir=None):
    """Run full ACME DNS-01 flow for *.domain. Returns (success, message)."""
    if cert_dir is None:
        cert_dir = WILDCARD_DIR
    _ensure_dirs()

    try:
        import josepy as jose
        from acme import challenges, client, messages

        # 1. Load/create account key
        account_key_crypto = _get_or_create_account_key()
        account_key = jose.JWKRSA(key=account_key_crypto)

        # 2. Create ACME client
        net = client.ClientNetwork(account_key, user_agent="KytranMail/1.0")
        directory = messages.Directory.from_json(
            net.get(ACME_DIRECTORY).json()
        )
        acme_client = client.ClientV2(directory, net)

        # 3. Register or load account
        if os.path.exists(ACCOUNT_URI_PATH):
            with open(ACCOUNT_URI_PATH) as f:
                account_uri = f.read().strip()
            regr = messages.RegistrationResource(
                uri=account_uri,
                body=messages.Registration(),
            )
            acme_client.net.account = regr
        else:
            regr = acme_client.new_account(
                messages.NewRegistration.from_data(
                    terms_of_service_agreed=True
                )
            )
            with open(ACCOUNT_URI_PATH, "w") as f:
                f.write(regr.uri)
            logger.info(f"[SSL] Registered ACME account: {regr.uri}")

        # 4. Request certificate for *.domain
        wildcard = f"*.{domain}"
        order = acme_client.new_order(
            jose.json_util.encode_b64jose(
                x509.CertificateSigningRequestBuilder()
                .subject_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, wildcard)]))
                .add_extension(
                    x509.SubjectAlternativeName([x509.DNSName(wildcard)]),
                    critical=False,
                )
                .sign(account_key_crypto, hashes.SHA256())
                .public_bytes(serialization.Encoding.DER)
            )
        )

        # 5. Find DNS-01 challenge
        authz = order.authorizations[0]
        dns_challenge = None
        for challenge in authz.body.challenges:
            if isinstance(challenge.chall, challenges.DNS01):
                dns_challenge = challenge
                break

        if not dns_challenge:
            return False, "No DNS-01 challenge offered by ACME server"

        # 6. Compute challenge response
        response, validation = dns_challenge.response_and_validation(account_key)
        challenge_name = "_acme-challenge"

        # 7. Create TXT record via Hostinger
        _hostinger_create_txt_record(domain, challenge_name, validation)

        # 8. Wait for DNS propagation
        fqdn = f"_acme-challenge.{domain}"
        if not _wait_for_dns_propagation(fqdn, validation):
            return False, f"DNS propagation timeout for {fqdn}"

        # 9. Answer challenge
        acme_client.answer_challenge(dns_challenge, response)

        # 10. Poll for cert
        order = acme_client.poll_and_finalize(
            order,
            deadline=datetime.now(timezone.utc).replace(
                second=0, microsecond=0
            ),
        )

        # 11. Save cert
        fullchain_path = os.path.join(cert_dir, "fullchain.pem")
        key_path = os.path.join(cert_dir, "privkey.pem")

        with open(fullchain_path, "w") as f:
            f.write(order.fullchain_pem)
        os.chmod(fullchain_path, 0o644)

        with open(key_path, "wb") as f:
            f.write(
                account_key_crypto.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        os.chmod(key_path, 0o600)

        # Save metadata
        info = get_cert_info(cert_dir)
        if info:
            info["renewed_at"] = datetime.now(timezone.utc).isoformat()
            with open(os.path.join(cert_dir, "cert-meta.json"), "w") as f:
                json.dump(info, f, indent=2)

        # 12. Cleanup TXT record
        try:
            _hostinger_delete_txt_record(domain, challenge_name, validation)
        except Exception as e:
            logger.warning(f"[SSL] Failed to cleanup TXT record: {e}")

        return True, f"Wildcard cert renewed for *.{domain}, expires {info['expires_at']}"

    except Exception as e:
        logger.error(f"[SSL] Renewal failed: {e}", exc_info=True)
        return False, str(e)
```

NOTE: The `new_order` call above uses the CSR directly. The actual `acme` library API may differ slightly — the implementer should check the `acme` library docs (use context7 MCP) and adjust the order creation to match the actual API. The key flow is: create order → get DNS challenge → answer it → finalize → get cert.

- [ ] **Step 2: Commit**

```bash
git add ai_bridge/cert_manager.py
git commit -m "feat(ssl): add cert manager — ACME DNS-01 + Hostinger DNS + cert storage"
```

---

## Task 2: Agent Loop Job Registration

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add the job method**

Find the last job method in `agent_loop.py` (search for the last `def _` method before the class ends). Add this method:

```python
def _renew_fleet_ssl(self):
    """Job #61: Renew wildcard SSL cert if expiring within 30 days.
    Owned by Security & Compliance (V.I.G.I.L.)."""
    try:
        from ai_bridge.cert_manager import check_cert_expiry, renew_wildcard_cert

        cert_dir = "/opt/archie-fleet/certs/wildcard"
        cert_path = os.path.join(cert_dir, "fullchain.pem")
        days_left = check_cert_expiry(cert_path)

        if days_left > 30:
            logger.info(f"[SSL] Wildcard cert valid for {days_left} more days, skipping renewal")
            return

        if days_left == -1:
            logger.info("[SSL] No wildcard cert found, attempting first issuance...")
        else:
            logger.info(f"[SSL] Cert expires in {days_left} days, starting renewal...")

        success, message = renew_wildcard_cert("kytranempowerment.com", cert_dir)

        if success:
            logger.info(f"[SSL] Renewal successful: {message}")
        else:
            logger.error(f"[SSL] Renewal failed: {message}")
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_notifications
                       (type, title, message, source, priority, visibility, is_read, created_at)
                       VALUES ('error', 'SSL Renewal Failed', %s, 'agent_loop', 'high', 'admin', FALSE, NOW())""",
                    (message,),
                )
    except Exception as e:
        logger.error(f"[SSL] Fleet SSL renewal error: {e}")
```

- [ ] **Step 2: Register the job in attach_jobs()**

Find the `attach_jobs()` method and add this job registration at the end of the job list, alongside the other jobs:

```python
# Job #61: Fleet SSL wildcard cert renewal (daily 03:00 UTC)
self.scheduler.add_job(
    with_app_context(self._renew_fleet_ssl),
    trigger=CronTrigger(hour=3, minute=0),
    id="fleet_ssl_renewal",
    name="Agent Loop: Fleet SSL Renewal",
    replace_existing=True,
)
```

Make sure `CronTrigger` is imported at the top of the file (it likely already is — check the existing imports).

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(ssl): register agent loop job #61 — daily wildcard cert renewal"
```

---

## Task 3: Hub Cert Serving API Endpoints

**Files:**
- Modify: `platform_v2/tools/starbase/fleet_routes.py`

- [ ] **Step 1: Add cert endpoints to fleet_routes.py**

Inside the `register_fleet_routes(bp, admin_required)` function, add these two endpoints alongside the existing fleet routes:

```python
# ── Cert Distribution ────────────────────────────────────────────

CERT_DIR = os.environ.get("FLEET_CERT_DIR", "/opt/archie-fleet/certs")
WILDCARD_CERT_DIR = os.path.join(CERT_DIR, "wildcard")

@bp.route("/api/fleet/certs/wildcard/check", methods=["GET"])
def fleet_cert_check():
    """Lightweight cert metadata check for fleet nodes."""
    # Verify request comes from mesh network
    remote_ip = request.remote_addr or ""
    if not remote_ip.startswith("100.64."):
        api_key = request.headers.get("X-Node-API-Key")
        if not api_key:
            return jsonify({"success": False, "error": "Mesh or API key required"}), 403

    cert_path = os.path.join(WILDCARD_CERT_DIR, "fullchain.pem")
    if not os.path.exists(cert_path):
        return jsonify({"success": False, "error": "No wildcard cert available"}), 404

    try:
        from cryptography import x509 as x509_mod

        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        cert = x509_mod.load_pem_x509_certificate(cert_pem)
        cert_hash = hashlib.sha256(cert_pem).hexdigest()

        return jsonify({
            "success": True,
            "expires_at": cert.not_valid_after_utc.isoformat(),
            "sha256": cert_hash,
            "domain": "*.kytranempowerment.com",
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/api/fleet/certs/wildcard", methods=["GET"])
def fleet_cert_download():
    """Full cert + key download for fleet nodes. Mesh-only or API key required."""
    remote_ip = request.remote_addr or ""
    if not remote_ip.startswith("100.64."):
        api_key = request.headers.get("X-Node-API-Key")
        if not api_key:
            return jsonify({"success": False, "error": "Mesh or API key required"}), 403

    cert_path = os.path.join(WILDCARD_CERT_DIR, "fullchain.pem")
    key_path = os.path.join(WILDCARD_CERT_DIR, "privkey.pem")

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        return jsonify({"success": False, "error": "No wildcard cert available"}), 404

    try:
        from cryptography import x509 as x509_mod

        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        with open(key_path, "rb") as f:
            key_pem = f.read()

        cert = x509_mod.load_pem_x509_certificate(cert_pem)
        cert_hash = hashlib.sha256(cert_pem).hexdigest()

        return jsonify({
            "success": True,
            "cert_pem": cert_pem.decode(),
            "key_pem": key_pem.decode(),
            "expires_at": cert.not_valid_after_utc.isoformat(),
            "sha256": cert_hash,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/starbase/fleet_routes.py
git commit -m "feat(ssl): add cert serving endpoints — check + download for fleet nodes"
```

---

## Task 4: Docker Volume Mount + Python Dependencies

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add cert volume mount to archie_platform**

Read `docker-compose.yml`, find the `archie_platform` volumes section. Add:

```yaml
      # Fleet SSL cert storage (wildcard cert for *.kytranempowerment.com)
      - /opt/archie-fleet/certs:/opt/archie-fleet/certs:rw
```

- [ ] **Step 2: Create the cert directory on the host**

```bash
sudo mkdir -p /opt/archie-fleet/certs/wildcard
sudo chown -R 1000:1000 /opt/archie-fleet/certs
```

- [ ] **Step 3: Install Python dependencies in the container**

Check if `acme`, `josepy`, and `cryptography` are already available. If not, add them to the platform's requirements or Dockerfile. Run:

```bash
docker exec archie_platform pip list 2>/dev/null | grep -iE "acme|josepy|cryptography"
```

If missing, add to the platform's `requirements.txt` or install in the Dockerfile. The `cryptography` package is likely already installed (it's a common dependency). `acme` and `josepy` may need to be added.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(ssl): mount cert volume + ensure ACME dependencies"
```

---

## Task 5: KSO Cert Sync Service

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/cert_service.py`

- [ ] **Step 1: Create cert_service.py**

```python
"""Cert sync service — pull wildcard cert from hub, save locally."""

import hashlib
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

HUB_URL = os.environ.get("KSM_HUB_URL", "http://100.64.0.2:3000")
NODE_API_KEY = os.environ.get("KSM_HUB_API_KEY", "")
LOCAL_CERT_DIR = os.environ.get("KSM_CERT_DIR", "/opt/archie-fleet/certs/wildcard")
SYNC_INTERVAL = 43200  # 12 hours


def get_local_cert_info():
    """Return local cert hash and expiry, or None if no cert."""
    cert_path = os.path.join(LOCAL_CERT_DIR, "fullchain.pem")
    if not os.path.exists(cert_path):
        return None
    try:
        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        return {"sha256": hashlib.sha256(cert_pem).hexdigest()}
    except Exception:
        return None


def check_and_sync_cert():
    """Check hub for newer cert, download if available. Returns True if updated."""
    try:
        # 1. Check hub cert metadata
        resp = requests.get(
            f"{HUB_URL}/tools/starbase/api/fleet/certs/wildcard/check",
            headers={"X-Node-API-Key": NODE_API_KEY},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"[CertSync] Hub cert check failed: {resp.status_code}")
            return False

        hub_info = resp.json()
        if not hub_info.get("success"):
            return False

        # 2. Compare with local cert
        local_info = get_local_cert_info()
        if local_info and local_info["sha256"] == hub_info["sha256"]:
            logger.debug("[CertSync] Local cert matches hub, no update needed")
            return False

        # 3. Download full cert
        resp = requests.get(
            f"{HUB_URL}/tools/starbase/api/fleet/certs/wildcard",
            headers={"X-Node-API-Key": NODE_API_KEY},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"[CertSync] Hub cert download failed: {resp.status_code}")
            return False

        data = resp.json()
        if not data.get("success"):
            return False

        # 4. Save locally
        os.makedirs(LOCAL_CERT_DIR, exist_ok=True)

        cert_path = os.path.join(LOCAL_CERT_DIR, "fullchain.pem")
        key_path = os.path.join(LOCAL_CERT_DIR, "privkey.pem")

        with open(cert_path, "w") as f:
            f.write(data["cert_pem"])
        os.chmod(cert_path, 0o644)

        with open(key_path, "w") as f:
            f.write(data["key_pem"])
        os.chmod(key_path, 0o600)

        logger.info(f"[CertSync] Updated wildcard cert, expires {data['expires_at']}")
        return True

    except Exception as e:
        logger.warning(f"[CertSync] Sync failed: {e}")
        return False


def start_cert_sync_thread():
    """Start background thread that syncs cert every 12h."""

    def _sync_loop():
        # Initial sync on startup (wait 30s for hub connectivity)
        time.sleep(30)
        check_and_sync_cert()

        while True:
            time.sleep(SYNC_INTERVAL)
            check_and_sync_cert()

    thread = threading.Thread(target=_sync_loop, daemon=True, name="cert-sync")
    thread.start()
    logger.info("[CertSync] Background cert sync started (interval: 12h)")
```

- [ ] **Step 2: Commit**

```bash
git add kytran-server-manager/kytran_server_manager/services/cert_service.py
git commit -m "feat(ssl): add KSO cert sync service — pull wildcard cert from hub"
```

---

## Task 6: Integration Test

- [ ] **Step 1: Recreate platform container with new volume**

```bash
sudo mkdir -p /opt/archie-fleet/certs/wildcard
sudo chown -R 1000:1000 /opt/archie-fleet/certs
docker compose up -d archie_platform
```

- [ ] **Step 2: Verify cert check endpoint (no cert yet)**

```bash
curl -s http://192.168.1.200:3000/tools/starbase/api/fleet/certs/wildcard/check \
  -H "X-Node-API-Key: test" | python3 -m json.tool
```

Expected: `{"success": false, "error": "No wildcard cert available"}` with 404 status.

- [ ] **Step 3: Verify cert_manager imports work**

```bash
docker exec archie_platform python3 -c "from ai_bridge.cert_manager import check_cert_expiry, get_cert_info; print('OK')"
```

Expected: `OK` (or import error if `acme`/`josepy` not installed — fix by installing deps).

- [ ] **Step 4: Test cert expiry check (no cert)**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.cert_manager import check_cert_expiry
print(f'Days left: {check_cert_expiry()}')
"
```

Expected: `Days left: -1`

- [ ] **Step 5: Verify Hostinger DNS API access**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.cert_manager import _hostinger_get_dns_records
records = _hostinger_get_dns_records('kytranempowerment.com')
print(f'Got {len(records)} records')
"
```

Expected: Shows record count (should be 10+).

- [ ] **Step 6: Test with Let's Encrypt staging (optional dry run)**

Only if you want to verify the full ACME flow without using production rate limits:

```bash
docker exec archie_platform python3 -c "
import os
os.environ['ACME_DIRECTORY'] = 'https://acme-staging-v02.api.letsencrypt.org/directory'
from ai_bridge.cert_manager import renew_wildcard_cert
success, msg = renew_wildcard_cert('kytranempowerment.com')
print(f'Success: {success}, Message: {msg}')
"
```

Expected: Either succeeds (staging cert saved) or shows specific error to debug.

- [ ] **Step 7: Verify catalog still shows 7 apps**

```bash
curl -s http://192.168.1.200:3000/tools/starbase/api/fleet/catalog | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Catalog: {d[\"count\"]} apps')"
```

Expected: 7 apps.

- [ ] **Step 8: Commit any fixes**

```bash
git add -A && git commit -m "feat(ssl): Fleet SSL Manager complete — ACME DNS-01 + cert distribution"
```
