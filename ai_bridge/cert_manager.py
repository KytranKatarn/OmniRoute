"""
cert_manager.py — Wildcard SSL cert renewal via ACME DNS-01 + Hostinger DNS API.

Public API:
    check_cert_expiry(cert_path) -> int
    get_cert_info(cert_dir) -> dict | None
    renew_wildcard_cert(domain, cert_dir) -> (bool, str)

Dependencies: cryptography, requests (both in container).
ACME protocol implemented directly — no acme/josepy packages needed.
"""

import base64
import hashlib
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CERT_DIR = "/opt/archie-fleet/certs"
WILDCARD_SUBDIR = "wildcard"

ACME_DIRECTORY = os.getenv(
    "ACME_DIRECTORY",
    "https://acme-v02.api.letsencrypt.org/directory",
)
HOSTINGER_API_BASE = "https://developers.hostinger.com"
HOSTINGER_API_KEY = os.getenv("HOSTINGER_API_KEY", "")

DNS_PROPAGATION_TIMEOUT = 300  # seconds
DNS_POLL_INTERVAL = 10  # seconds
ACME_POLL_INTERVAL = 3
ACME_POLL_TIMEOUT = 120

CERT_RSA_KEY_SIZE = 2048
ACCOUNT_RSA_KEY_SIZE = 2048


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url-decode with padding restoration."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _int_to_b64url(n: int) -> str:
    """Encode a positive integer as base64url big-endian bytes."""
    byte_len = (n.bit_length() + 7) // 8
    return _b64url(n.to_bytes(byte_len, byteorder="big"))


# ---------------------------------------------------------------------------
# ACME JWS signing
# ---------------------------------------------------------------------------


def _load_or_create_account_key(cert_dir: str) -> rsa.RSAPrivateKey:
    """Load existing account.key or generate a new one."""
    key_path = Path(cert_dir) / "account.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        pem = key_path.read_bytes()
        return serialization.load_pem_private_key(pem, password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=ACCOUNT_RSA_KEY_SIZE)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    os.chmod(str(key_path), 0o600)
    logger.info("Generated new ACME account key at %s", key_path)
    return key


def _jwk(account_key: rsa.RSAPrivateKey) -> dict:
    """Build a JWK dict from the account RSA key."""
    pub = account_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "n": _int_to_b64url(pub.n),
        "e": _int_to_b64url(pub.e),
    }


def _thumbprint(jwk_dict: dict) -> str:
    """JWK thumbprint (SHA-256) per RFC 7638."""
    ordered = json.dumps(
        {k: jwk_dict[k] for k in ("e", "kty", "n")},
        separators=(",", ":"),
        sort_keys=True,
    )
    return _b64url(hashlib.sha256(ordered.encode("ascii")).digest())


def _sign_jws(
    account_key: rsa.RSAPrivateKey,
    url: str,
    payload: dict | str | None,
    nonce: str,
    kid: str | None = None,
) -> dict:
    """
    Build a JWS (Flattened JSON Serialization) for ACME.
    payload=None  -> POST-as-GET (empty payload)
    payload=""    -> empty string (new-account uses actual dict)
    """
    header = {"alg": "RS256", "nonce": nonce, "url": url}
    if kid:
        header["kid"] = kid
    else:
        header["jwk"] = _jwk(account_key)

    protected = _b64url(json.dumps(header).encode("utf-8"))

    if payload is None:
        # POST-as-GET: empty string payload
        payload_b64 = ""
    elif isinstance(payload, str) and payload == "":
        payload_b64 = ""
    else:
        payload_b64 = _b64url(json.dumps(payload).encode("utf-8"))

    signing_input = f"{protected}.{payload_b64}".encode("ascii")
    signature = account_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())

    return {
        "protected": protected,
        "payload": payload_b64,
        "signature": _b64url(signature),
    }


# ---------------------------------------------------------------------------
# ACME HTTP helpers
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers["Content-Type"] = "application/jose+json"
_session.headers["User-Agent"] = "ARCHIE-CertManager/1.0"


class _AcmeClient:
    """Lightweight ACME v2 client."""

    def __init__(self, account_key: rsa.RSAPrivateKey, cert_dir: str):
        self.account_key = account_key
        self.cert_dir = cert_dir
        self.kid: str | None = None
        self._nonce: str | None = None
        self._directory: dict = {}

    # -- directory & nonce --------------------------------------------------

    def fetch_directory(self):
        resp = _session.get(ACME_DIRECTORY, timeout=30)
        resp.raise_for_status()
        self._directory = resp.json()
        logger.debug("ACME directory: %s", list(self._directory.keys()))

    def _get_nonce(self) -> str:
        if self._nonce:
            n = self._nonce
            self._nonce = None
            return n
        resp = _session.head(self._directory["newNonce"], timeout=15)
        return resp.headers["Replay-Nonce"]

    def _save_nonce(self, resp: requests.Response):
        if "Replay-Nonce" in resp.headers:
            self._nonce = resp.headers["Replay-Nonce"]

    # -- signed POST --------------------------------------------------------

    def _post(self, url: str, payload=None) -> requests.Response:
        nonce = self._get_nonce()
        body = _sign_jws(self.account_key, url, payload, nonce, kid=self.kid)
        resp = _session.post(url, json=body, timeout=30)
        self._save_nonce(resp)
        return resp

    # -- account ------------------------------------------------------------

    def register_or_login(self):
        uri_path = Path(self.cert_dir) / "account.uri"

        if uri_path.exists():
            self.kid = uri_path.read_text().strip()
            logger.info("Using existing ACME account: %s", self.kid)
            # Verify account still valid
            resp = self._post(self.kid, None)
            if resp.status_code in (200, 201):
                return
            logger.warning(
                "Existing account URI invalid (%s), re-registering", resp.status_code
            )

        payload = {"termsOfServiceAgreed": True}
        resp = self._post(self._directory["newAccount"], payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"ACME account registration failed: {resp.status_code} {resp.text}")

        self.kid = resp.headers.get("Location", resp.json().get("kid"))
        if not self.kid:
            raise RuntimeError("No account URL returned from ACME server")

        uri_path.write_text(self.kid)
        logger.info("Registered ACME account: %s", self.kid)

    # -- order --------------------------------------------------------------

    def new_order(self, domain: str) -> dict:
        identifiers = [
            {"type": "dns", "value": f"*.{domain}"},
            {"type": "dns", "value": domain},
        ]
        resp = self._post(
            self._directory["newOrder"], {"identifiers": identifiers}
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"ACME newOrder failed: {resp.status_code} {resp.text}")
        order = resp.json()
        order["_url"] = resp.headers.get("Location", "")
        return order

    # -- authorization & challenge ------------------------------------------

    def get_authorization(self, authz_url: str) -> dict:
        resp = self._post(authz_url, None)
        resp.raise_for_status()
        return resp.json()

    def get_dns01_challenge(self, authz: dict) -> dict | None:
        for ch in authz.get("challenges", []):
            if ch["type"] == "dns-01":
                return ch
        return None

    def dns01_txt_value(self, token: str) -> str:
        """Compute the TXT record value for a dns-01 challenge."""
        tp = _thumbprint(_jwk(self.account_key))
        key_authz = f"{token}.{tp}"
        digest = hashlib.sha256(key_authz.encode("ascii")).digest()
        return _b64url(digest)

    def answer_challenge(self, challenge_url: str) -> dict:
        resp = self._post(challenge_url, {})
        if resp.status_code not in (200, 202):
            raise RuntimeError(
                f"ACME challenge response failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def poll_authorization(self, authz_url: str) -> dict:
        deadline = time.time() + ACME_POLL_TIMEOUT
        while time.time() < deadline:
            authz = self.get_authorization(authz_url)
            status = authz.get("status")
            if status == "valid":
                return authz
            if status in ("invalid", "deactivated", "expired", "revoked"):
                raise RuntimeError(f"Authorization failed: status={status}")
            time.sleep(ACME_POLL_INTERVAL)
        raise RuntimeError("Authorization timed out")

    # -- finalize -----------------------------------------------------------

    def finalize_order(self, finalize_url: str, csr_der: bytes) -> dict:
        payload = {"csr": _b64url(csr_der)}
        resp = self._post(finalize_url, payload)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"ACME finalize failed: {resp.status_code} {resp.text}")
        return resp.json()

    def poll_order(self, order_url: str) -> dict:
        deadline = time.time() + ACME_POLL_TIMEOUT
        while time.time() < deadline:
            resp = self._post(order_url, None)
            resp.raise_for_status()
            order = resp.json()
            if order["status"] == "valid":
                return order
            if order["status"] in ("invalid",):
                raise RuntimeError(f"Order invalid: {order}")
            time.sleep(ACME_POLL_INTERVAL)
        raise RuntimeError("Order finalize timed out")

    def download_cert(self, cert_url: str) -> str:
        resp = self._post(cert_url, None)
        resp.raise_for_status()
        return resp.text


# ---------------------------------------------------------------------------
# CSR generation
# ---------------------------------------------------------------------------


def _generate_cert_key_and_csr(
    domain: str, cert_dir: str
) -> tuple[rsa.RSAPrivateKey, bytes]:
    """Generate a fresh RSA private key and CSR for wildcard + apex domain."""
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=CERT_RSA_KEY_SIZE
    )

    # Save private key immediately
    wc_dir = Path(cert_dir) / WILDCARD_SUBDIR
    wc_dir.mkdir(parents=True, exist_ok=True)
    privkey_path = wc_dir / "privkey.pem"
    privkey_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    os.chmod(str(privkey_path), 0o600)

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, f"*.{domain}")]))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(f"*.{domain}"),
                    x509.DNSName(domain),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    return key, csr.public_bytes(serialization.Encoding.DER)


# ---------------------------------------------------------------------------
# Hostinger DNS API helpers
# ---------------------------------------------------------------------------


def _hostinger_headers() -> dict:
    key = HOSTINGER_API_KEY or os.getenv("HOSTINGER_API_KEY", "")
    if not key:
        raise RuntimeError("HOSTINGER_API_KEY env var is not set")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _hostinger_get_records(domain: str) -> list[dict]:
    """GET all DNS records for the domain."""
    url = f"{HOSTINGER_API_BASE}/api/dns/v1/zones/{domain}"
    resp = requests.get(url, headers=_hostinger_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _hostinger_put_records(domain: str, records: list[dict]) -> None:
    """PUT (replace) all DNS records for the domain."""
    url = f"{HOSTINGER_API_BASE}/api/dns/v1/zones/{domain}"
    resp = requests.put(
        url, headers=_hostinger_headers(), json={"overwrite": True, "zone": records}, timeout=30
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(
            f"Hostinger DNS PUT failed: {resp.status_code} {resp.text}"
        )


def _add_acme_txt_record(domain: str, txt_value: str) -> None:
    """Add _acme-challenge TXT record, preserving existing records."""
    records = _hostinger_get_records(domain)
    logger.info(
        "Fetched %d existing DNS records for %s", len(records), domain
    )

    # Add the challenge TXT record (Hostinger API v1 zone format)
    records.append(
        {
            "name": "_acme-challenge",
            "type": "TXT",
            "records": [{"content": txt_value}],
            "ttl": 60,
        }
    )

    _hostinger_put_records(domain, records)
    logger.info("Added _acme-challenge TXT record: %s...", txt_value[:20])


def _remove_acme_txt_records(domain: str) -> None:
    """Remove all _acme-challenge TXT records."""
    records = _hostinger_get_records(domain)
    filtered = [
        r
        for r in records
        if not (
            r.get("type", "").upper() == "TXT"
            and r.get("name", "").startswith("_acme-challenge")
        )
    ]
    removed = len(records) - len(filtered)
    if removed > 0:
        _hostinger_put_records(domain, filtered)
        logger.info("Removed %d _acme-challenge TXT record(s)", removed)
    else:
        logger.debug("No _acme-challenge TXT records to remove")


# ---------------------------------------------------------------------------
# DNS propagation check
# ---------------------------------------------------------------------------


def _check_dns_propagation(domain: str, expected_value: str) -> bool:
    """Check if _acme-challenge.{domain} TXT record has propagated via Google DNS."""
    fqdn = f"_acme-challenge.{domain}"
    try:
        result = subprocess.run(
            ["dig", "+short", "TXT", fqdn, "@8.8.8.8"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip().replace('"', "")
        # dig can return multiple lines for multiple TXT records
        for line in output.splitlines():
            if expected_value in line.strip():
                return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("DNS propagation check failed: %s", exc)
        return False


def _wait_for_dns_propagation(domain: str, expected_value: str) -> bool:
    """Wait up to DNS_PROPAGATION_TIMEOUT for TXT record to propagate."""
    deadline = time.time() + DNS_PROPAGATION_TIMEOUT
    logger.info(
        "Waiting for DNS propagation of _acme-challenge.%s (timeout %ds)...",
        domain,
        DNS_PROPAGATION_TIMEOUT,
    )
    while time.time() < deadline:
        if _check_dns_propagation(domain, expected_value):
            logger.info("DNS propagation confirmed for _acme-challenge.%s", domain)
            return True
        time.sleep(DNS_POLL_INTERVAL)
    logger.error(
        "DNS propagation timed out after %ds for _acme-challenge.%s",
        DNS_PROPAGATION_TIMEOUT,
        domain,
    )
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_cert_expiry(cert_path: str | None = None) -> int:
    """Return days until cert expires. -1 if cert doesn't exist."""
    if cert_path is None:
        cert_path = os.path.join(DEFAULT_CERT_DIR, WILDCARD_SUBDIR, "fullchain.pem")

    path = Path(cert_path)
    if not path.exists():
        return -1

    try:
        pem = path.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
        delta = cert.not_valid_after_utc - datetime.now(timezone.utc)
        return max(int(delta.total_seconds() // 86400), 0)
    except Exception:
        logger.exception("Failed to read cert expiry from %s", cert_path)
        return -1


def get_cert_info(cert_dir: str | None = None) -> dict | None:
    """Return cert metadata or None if cert doesn't exist."""
    if cert_dir is None:
        cert_dir = os.path.join(DEFAULT_CERT_DIR, WILDCARD_SUBDIR)

    chain_path = Path(cert_dir) / "fullchain.pem"
    key_path = Path(cert_dir) / "privkey.pem"

    if not chain_path.exists():
        return None

    try:
        pem = chain_path.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)

        # SHA-256 fingerprint
        sha256 = cert.fingerprint(hashes.SHA256()).hex(":")

        # Extract SANs
        try:
            san = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            domains = san.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            domains = []

        # Issuer
        issuer_parts = []
        for attr in cert.issuer:
            issuer_parts.append(f"{attr.oid._name}={attr.value}")
        issuer = ", ".join(issuer_parts)

        return {
            "expires_at": cert.not_valid_after_utc.isoformat(),
            "sha256": sha256,
            "domains": domains,
            "issuer": issuer,
            "has_key": key_path.exists(),
        }
    except Exception:
        logger.exception("Failed to read cert info from %s", cert_dir)
        return None


def renew_wildcard_cert(
    domain: str = "kytranempowerment.com",
    cert_dir: str | None = None,
) -> tuple[bool, str]:
    """
    Full ACME DNS-01 flow for wildcard cert renewal.
    Returns (success, message).
    """
    if cert_dir is None:
        cert_dir = DEFAULT_CERT_DIR

    wc_dir = os.path.join(cert_dir, WILDCARD_SUBDIR)

    logger.info("Starting wildcard cert renewal for *.%s", domain)

    # ------------------------------------------------------------------
    # 1. Load / create account key
    # ------------------------------------------------------------------
    try:
        account_key = _load_or_create_account_key(cert_dir)
    except Exception as exc:
        return False, f"Failed to load/create account key: {exc}"

    # ------------------------------------------------------------------
    # 2. Initialize ACME client
    # ------------------------------------------------------------------
    client = _AcmeClient(account_key, cert_dir)
    try:
        client.fetch_directory()
        client.register_or_login()
    except Exception as exc:
        return False, f"ACME initialization failed: {exc}"

    # ------------------------------------------------------------------
    # 3. Create new order
    # ------------------------------------------------------------------
    try:
        order = client.new_order(domain)
        logger.info("Created ACME order: %s", order.get("_url", ""))
    except Exception as exc:
        return False, f"ACME order creation failed: {exc}"

    # ------------------------------------------------------------------
    # 4. Process DNS-01 authorizations
    # ------------------------------------------------------------------
    txt_values = []
    authz_urls = order.get("authorizations", [])
    challenge_urls = []

    try:
        for authz_url in authz_urls:
            authz = client.get_authorization(authz_url)
            challenge = client.get_dns01_challenge(authz)
            if not challenge:
                return False, f"No dns-01 challenge found in authorization {authz_url}"

            txt_value = client.dns01_txt_value(challenge["token"])
            txt_values.append(txt_value)
            challenge_urls.append((challenge["url"], authz_url))

            logger.info(
                "Authorization %s: need TXT=%s...",
                authz.get("identifier", {}).get("value", "?"),
                txt_value[:20],
            )

        # Add all TXT records first, then wait for propagation.
        # Both wildcard and apex use the same _acme-challenge name, so
        # we may need multiple TXT records.
        records = _hostinger_get_records(domain)
        for tv in txt_values:
            records.append(
                {
                    "type": "TXT",
                    "name": "_acme-challenge",
                    "content": tv,
                    "ttl": 60,
                }
            )
        _hostinger_put_records(domain, records)
        logger.info("Set %d _acme-challenge TXT record(s)", len(txt_values))

    except Exception as exc:
        _safe_cleanup(domain)
        return False, f"DNS record setup failed: {exc}"

    # ------------------------------------------------------------------
    # 5. Wait for DNS propagation (check last value — if it's there,
    #    the others should be too since they went in the same PUT)
    # ------------------------------------------------------------------
    if not _wait_for_dns_propagation(domain, txt_values[-1]):
        _safe_cleanup(domain)
        return False, "DNS propagation timed out"

    # ------------------------------------------------------------------
    # 6. Answer challenges and poll for valid
    # ------------------------------------------------------------------
    try:
        for ch_url, az_url in challenge_urls:
            client.answer_challenge(ch_url)

        for _, az_url in challenge_urls:
            client.poll_authorization(az_url)
            logger.info("Authorization %s validated", az_url)

    except Exception as exc:
        _safe_cleanup(domain)
        return False, f"Challenge validation failed: {exc}"

    # ------------------------------------------------------------------
    # 7. Generate cert key + CSR and finalize
    # ------------------------------------------------------------------
    try:
        _cert_key, csr_der = _generate_cert_key_and_csr(domain, cert_dir)
        finalize_resp = client.finalize_order(order["finalize"], csr_der)

        # If status is "processing", poll the order URL
        order_url = order.get("_url") or finalize_resp.get("_url", "")
        if finalize_resp.get("status") == "processing" and order_url:
            finalize_resp = client.poll_order(order_url)

        cert_url = finalize_resp.get("certificate")
        if not cert_url:
            _safe_cleanup(domain)
            return False, "No certificate URL in finalized order"

        fullchain = client.download_cert(cert_url)

    except Exception as exc:
        _safe_cleanup(domain)
        return False, f"Order finalization failed: {exc}"

    # ------------------------------------------------------------------
    # 8. Save cert + metadata
    # ------------------------------------------------------------------
    try:
        wc_path = Path(wc_dir)
        wc_path.mkdir(parents=True, exist_ok=True)

        chain_path = wc_path / "fullchain.pem"
        chain_path.write_text(fullchain)
        os.chmod(str(chain_path), 0o644)

        # Write metadata
        meta = {
            "domain": domain,
            "renewed_at": datetime.now(timezone.utc).isoformat(),
            "acme_directory": ACME_DIRECTORY,
            "identifiers": [f"*.{domain}", domain],
        }
        meta_path = wc_path / "cert-meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        logger.info("Saved wildcard cert to %s", wc_path)

    except Exception as exc:
        return False, f"Failed to save cert files: {exc}"

    # ------------------------------------------------------------------
    # 9. Cleanup DNS records
    # ------------------------------------------------------------------
    _safe_cleanup(domain)

    # ------------------------------------------------------------------
    # 10. Verify the cert we just saved
    # ------------------------------------------------------------------
    days = check_cert_expiry(str(Path(wc_dir) / "fullchain.pem"))
    if days <= 0:
        return False, "Cert saved but could not verify expiry — check fullchain.pem"

    return True, f"Wildcard cert renewed for *.{domain} — expires in {days} days"


def _safe_cleanup(domain: str) -> None:
    """Remove ACME TXT records, swallowing errors."""
    try:
        _remove_acme_txt_records(domain)
    except Exception:
        logger.exception("Failed to clean up ACME DNS records for %s", domain)
