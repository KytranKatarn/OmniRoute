"""API key format, hashing and verification — STDLIB ONLY (task #2138).

No Flask, no SQLAlchemy, no project imports, for the reason recorded in
``rate_policy.py``: a guard that pulls in Flask reports ``s`` (skipped) on a
machine without it while the suite still prints "passed" (KB #290497). Key
handling is exactly the code that must not be silently untested.

FORMAT   wtf_<prefix>_<secret>
         prefix  12 url-safe chars — PUBLIC. Stored in clear, indexed, and shown
                 in the UI so a user can identify a key without revealing it.
         secret  43 url-safe chars ≈ 256 bits — never stored, shown once.

STORAGE  Only ``sha256(secret)`` is persisted. The full key cannot be recovered
         from the database, so a DB leak does not hand over working credentials.
         Plain SHA-256 is correct HERE and would be wrong for a password: the
         secret is 256 bits of CSPRNG output, so there is no dictionary to run.
         Stretching (bcrypt/PBKDF2) buys nothing against that and would cost a
         KDF on every API request.

COMPARE  ``hmac.compare_digest``. A plain ``==`` on a hash leaks timing, and the
         prefix lookup means an attacker can aim at one specific row.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string

PREFIX_LEN = 12
SECRET_LEN = 43            # 43 base62 chars ~ 256 bits
KEY_NAMESPACE = "wtf"

# ⚠️ ALNUM ONLY — deliberately NOT base64url, and not `secrets.token_urlsafe`.
# `_` is the field separator in `wtf_<prefix>_<secret>`, and token_urlsafe emits
# both `_` and `-`. A secret containing an underscore splits into four parts and
# `parse_key` rejects it, so the key would be minted successfully, shown to the
# user once, and then never work. With 55 characters drawn from a 64-symbol
# alphabet that is the common case, not an edge case. Caught by
# tests/test_api_plans.py, which is why that test generates and round-trips a
# real key instead of asserting on a hand-written literal.
_ALPHABET = string.ascii_letters + string.digits
_ALPHABET_OK = set(_ALPHABET)


def generate_key() -> tuple[str, str, str]:
    """Mint a new key.

    Returns ``(full_key, prefix, key_hash)``. The caller stores prefix+hash and
    shows ``full_key`` to the user EXACTLY ONCE — there is no recovery path, by
    design.
    """
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(PREFIX_LEN))
    secret = "".join(secrets.choice(_ALPHABET) for _ in range(SECRET_LEN))
    full = f"{KEY_NAMESPACE}_{prefix}_{secret}"
    return full, prefix, hash_secret(secret)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_key(raw: str) -> tuple[str, str] | None:
    """Split a presented key into ``(prefix, secret)``, or None if malformed.

    Fail-closed and allocation-free on junk: a caller can send anything, and a
    malformed key must never become a DB query with attacker-controlled shape.
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if len(raw) > 200:                      # nothing legitimate is this long
        return None
    parts = raw.split("_")
    if len(parts) != 3:
        return None
    ns, prefix, secret = parts
    if ns != KEY_NAMESPACE:
        return None
    if len(prefix) != PREFIX_LEN or not prefix:
        return None
    if not secret:
        return None
    if not set(prefix) <= _ALPHABET_OK or not set(secret) <= _ALPHABET_OK:
        return None
    return prefix, secret


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time check of a presented secret against the stored hash."""
    if not secret or not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(secret), stored_hash)


def redact(full_key: str) -> str:
    """Display form for logs and UI — prefix only, secret never echoed."""
    parsed = parse_key(full_key)
    if not parsed:
        return "<invalid key>"
    return f"{KEY_NAMESPACE}_{parsed[0]}_" + "*" * 8
