"""
A.R.C.H.I.E. Platform - Google Drive Backup Encryption
=======================================================

AES-256-GCM encryption for cloud backups with PBKDF2 key derivation.

Encrypted file format: [16-byte salt][16-byte nonce][ciphertext][16-byte tag]
"""

import os
import hashlib
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256, HMAC as CryptoHMAC

# PBKDF2 iterations - OWASP recommended minimum for SHA-256
PBKDF2_ITERATIONS = 600_000
SALT_SIZE = 16
NONCE_SIZE = 16
TAG_SIZE = 16
# Process files in 64KB chunks for memory efficiency
CHUNK_READ_SIZE = 64 * 1024

# ---------------------------------------------------------------------------
# TWO ENCRYPTION FORMATS EXIST IN GOOGLE DRIVE — this module must read BOTH.
#
# 1. "gcm"         — written by encrypt_file() below (the UI upload path).
#                    [16B salt][16B nonce][ciphertext][16B tag], PBKDF2 600k.
# 2. "openssl-cbc" — written by the NIGHTLY host job scripts/backup/
#                    tier_sync_gdrive.py via:
#                      openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt
#                    Layout: b"Salted__"[8B salt][CBC ciphertext, PKCS#7].
#                    openssl derives KEY(32)+IV(16) = 48 bytes from one
#                    PBKDF2-HMAC-SHA256 pass (its default digest for `enc`).
#
# EVERY object currently in Drive is format 2 — the nightly job produced all of
# them. decrypt_file() previously assumed format 1 unconditionally, so the UI's
# "Download" could not restore a single real off-site backup even with the
# correct passphrase (#5124). Detect the format; never assume it.
# ---------------------------------------------------------------------------
OPENSSL_MAGIC = b"Salted__"
OPENSSL_SALT_SIZE = 8
OPENSSL_PBKDF2_ITERATIONS = 200_000  # MUST match tier_sync_gdrive.py's -iter


def detect_format(input_path: str) -> str:
    """Return 'openssl-cbc' or 'gcm' by sniffing the file header."""
    with open(input_path, "rb") as fh:
        if fh.read(len(OPENSSL_MAGIC)) == OPENSSL_MAGIC:
            return "openssl-cbc"
    return "gcm"


def _decrypt_openssl_cbc(input_path: str, output_path: str, passphrase: str, on_progress=None) -> bool:
    """Decrypt an `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt` file.

    CBC is unauthenticated, so unlike the GCM path there is no tag to verify.
    A wrong passphrase therefore surfaces as invalid PKCS#7 padding rather than
    a clean integrity failure — we translate that into the same ValueError the
    GCM path raises so callers can treat both identically.
    """
    file_size = os.path.getsize(input_path)
    header_len = len(OPENSSL_MAGIC) + OPENSSL_SALT_SIZE
    if file_size <= header_len:
        raise ValueError("File too small to be a valid encrypted backup")

    with open(input_path, "rb") as fin:
        fin.read(len(OPENSSL_MAGIC))  # magic, already sniffed
        salt = fin.read(OPENSSL_SALT_SIZE)

        key_iv = PBKDF2(
            passphrase.encode("utf-8"),
            salt,
            dkLen=48,
            count=OPENSSL_PBKDF2_ITERATIONS,
            prf=lambda p, s: CryptoHMAC.new(p, s, SHA256).digest(),
        )
        cipher = AES.new(key_iv[:32], AES.MODE_CBC, iv=key_iv[32:48])

        remaining = file_size - header_len
        bytes_processed = 0
        # Hold the trailing block back so PKCS#7 padding is stripped only there.
        carry = b""
        with open(output_path, "wb") as fout:
            while remaining > 0:
                read_size = min(CHUNK_READ_SIZE, remaining)
                chunk = fin.read(read_size)
                if not chunk:
                    break
                remaining -= len(chunk)
                bytes_processed += len(chunk)
                block = carry + cipher.decrypt(chunk)
                carry, block = block[-16:], block[:-16]
                if block:
                    fout.write(block)
                if on_progress:
                    on_progress(bytes_processed, file_size - header_len)

            if not carry:
                raise ValueError("Decryption failed: empty ciphertext")
            pad = carry[-1]
            if not 1 <= pad <= 16 or carry[-pad:] != bytes([pad]) * pad:
                raise ValueError("Decryption failed: wrong passphrase or corrupted file")
            if carry[:-pad]:
                fout.write(carry[:-pad])

    return True


def decrypt_with_candidates(input_path: str, output_path: str, candidates) -> str:
    """Try each (label, passphrase) in order; return the label that worked.

    ⚠️ The Drive tier is NOT single-key. Measured 2026-07-22 against live objects:
      • `<run>/config/*.enc`  → BACKUP_CONFIG_PASSPHRASE
      • everything else       → BACKUP_GDRIVE_PASSPHRASE
    because component_config.sh encrypts the config tier upstream and
    tier_sync_gdrive.py passes an already-`.enc` file through without
    re-encrypting it. Assuming one passphrase leaves part of the off-site set
    unrecoverable, so callers pass an ordered candidate list instead (#5124).

    CBC is unauthenticated, so a wrong key is detected only by invalid PKCS#7
    padding (~1/256 chance of a false accept per try). Order candidates by the
    object's path so the FIRST attempt is the expected one; the fallback exists
    for mislabelled or legacy objects, not as the primary mechanism.
    """
    last_error = None
    for label, passphrase in candidates:
        if not passphrase:
            continue
        try:
            decrypt_file(input_path, output_path, passphrase)
            return label
        except Exception as exc:  # wrong key, bad padding, or truncated file
            last_error = exc
    raise ValueError(f"No configured passphrase could decrypt this backup ({last_error})")


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from passphrase using PBKDF2-HMAC-SHA256."""
    return PBKDF2(
        passphrase.encode("utf-8"),
        salt,
        dkLen=32,
        count=PBKDF2_ITERATIONS,
        prf=lambda p, s: CryptoHMAC.new(p, s, SHA256).digest(),
    )


def encrypt_file(input_path: str, output_path: str, passphrase: str, on_progress=None) -> dict:
    """
    Encrypt a file with AES-256-GCM.

    Args:
        input_path: Path to plaintext file
        output_path: Path for encrypted output
        passphrase: Encryption passphrase
        on_progress: Optional callback(bytes_processed, total_bytes)

    Returns:
        dict with salt, nonce, tag (all hex), and original_size
    """
    salt = os.urandom(SALT_SIZE)
    key = derive_key(passphrase, salt)

    cipher = AES.new(key, AES.MODE_GCM, nonce=os.urandom(NONCE_SIZE))

    file_size = os.path.getsize(input_path)
    bytes_processed = 0

    with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
        # Write header: salt + nonce
        fout.write(salt)
        fout.write(cipher.nonce)

        # Encrypt in chunks
        while True:
            chunk = fin.read(CHUNK_READ_SIZE)
            if not chunk:
                break
            encrypted_chunk = cipher.encrypt(chunk)
            fout.write(encrypted_chunk)
            bytes_processed += len(chunk)
            if on_progress:
                on_progress(bytes_processed, file_size)

        # Write authentication tag
        tag = cipher.digest()
        fout.write(tag)

    return {
        "salt": salt.hex(),
        "nonce": cipher.nonce.hex(),
        "tag": tag.hex(),
        "original_size": file_size,
        "encrypted_size": os.path.getsize(output_path),
    }


def decrypt_file(input_path: str, output_path: str, passphrase: str, on_progress=None) -> bool:
    """
    Decrypt an AES-256-GCM encrypted file.

    Args:
        input_path: Path to encrypted file
        output_path: Path for decrypted output
        passphrase: Decryption passphrase
        on_progress: Optional callback(bytes_processed, total_bytes)

    Returns:
        True if decryption and integrity check passed

    Raises:
        ValueError: If passphrase is wrong or file is tampered
    """
    # Nightly-uploaded objects are openssl AES-256-CBC, not GCM. Dispatch on the
    # actual header rather than assuming this module wrote the file (#5124).
    if detect_format(input_path) == "openssl-cbc":
        return _decrypt_openssl_cbc(input_path, output_path, passphrase, on_progress)

    file_size = os.path.getsize(input_path)
    # Encrypted payload size = total - salt - nonce - tag
    payload_size = file_size - SALT_SIZE - NONCE_SIZE - TAG_SIZE

    if payload_size < 0:
        raise ValueError("File too small to be a valid encrypted backup")

    with open(input_path, "rb") as fin:
        salt = fin.read(SALT_SIZE)
        nonce = fin.read(NONCE_SIZE)

        key = derive_key(passphrase, salt)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

        bytes_processed = 0
        with open(output_path, "wb") as fout:
            remaining = payload_size
            while remaining > 0:
                read_size = min(CHUNK_READ_SIZE, remaining)
                chunk = fin.read(read_size)
                if not chunk:
                    break
                decrypted_chunk = cipher.decrypt(chunk)
                fout.write(decrypted_chunk)
                remaining -= len(chunk)
                bytes_processed += len(chunk)
                if on_progress:
                    on_progress(bytes_processed, payload_size)

        # Read and verify authentication tag
        tag = fin.read(TAG_SIZE)
        try:
            cipher.verify(tag)
        except ValueError:
            # Clean up the partially decrypted file
            if os.path.exists(output_path):
                os.remove(output_path)
            raise ValueError("Decryption failed: wrong passphrase or corrupted file")

    return True


def hash_passphrase(passphrase: str) -> str:
    """Create SHA-256 hash of passphrase for storage/verification."""
    return hashlib.sha256(passphrase.encode("utf-8")).hexdigest()


def verify_passphrase(passphrase: str, stored_hash: str) -> bool:
    """Verify passphrase against stored hash."""
    return hashlib.sha256(passphrase.encode("utf-8")).hexdigest() == stored_hash
