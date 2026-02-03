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
