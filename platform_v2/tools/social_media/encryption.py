"""
Social Media Token Encryption
=============================
Fernet-based encryption for OAuth tokens.

Uses the SOCIAL_MEDIA_ENCRYPTION_KEY environment variable.
If not set, generates a key on first use and logs a warning.

Usage:
    from tools.social_media.encryption import encrypt_token, decrypt_token

    # Encrypt before storing
    encrypted = encrypt_token("my_access_token")

    # Decrypt when needed
    original = decrypt_token(encrypted)
"""

import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Encryption key - loaded from environment or generated
_fernet = None
_key_source = None


def _get_fernet():
    """Get or create Fernet instance."""
    global _fernet, _key_source

    if _fernet is not None:
        return _fernet

    # Try to load key from environment
    key = os.getenv("SOCIAL_MEDIA_ENCRYPTION_KEY")

    if key:
        _key_source = "environment"
        try:
            _fernet = Fernet(key.encode() if isinstance(key, str) else key)
            logger.info("Token encryption initialized from environment key")
        except Exception as e:
            logger.error(f"Invalid encryption key in environment: {e}")
            raise ValueError(
                'SOCIAL_MEDIA_ENCRYPTION_KEY is invalid. Generate new key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
    else:
        # Generate a key for development (NOT RECOMMENDED FOR PRODUCTION)
        _key_source = "generated"
        _fernet = Fernet(Fernet.generate_key())
        logger.warning(
            "SOCIAL_MEDIA_ENCRYPTION_KEY not set! "
            "Using generated key - tokens will be lost on restart. "
            "Generate a permanent key with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    return _fernet


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a token string.

    Args:
        plaintext: The token to encrypt

    Returns:
        Base64-encoded encrypted string (safe for database storage)
    """
    if not plaintext:
        return None

    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_token(encrypted: str) -> str:
    """
    Decrypt an encrypted token.

    Args:
        encrypted: Base64-encoded encrypted string from database

    Returns:
        Original plaintext token

    Raises:
        InvalidToken: If token cannot be decrypted (wrong key or corrupted)
    """
    if not encrypted:
        return None

    fernet = _get_fernet()
    try:
        decrypted_bytes = fernet.decrypt(encrypted.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt token - key may have changed")
        raise


def generate_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        Base64-encoded key string (safe for .env file)
    """
    return Fernet.generate_key().decode("utf-8")


def get_key_source() -> str:
    """
    Get the source of the current encryption key.

    Returns:
        'environment' if loaded from env, 'generated' if auto-generated
    """
    _get_fernet()  # Ensure initialized
    return _key_source


def validate_key(key: str) -> bool:
    """
    Validate that a string is a valid Fernet key.

    Args:
        key: Key string to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
        return True
    except Exception:
        return False


# Self-test when run directly
if __name__ == "__main__":
    print("Testing encryption module...")

    # Generate and display a new key
    new_key = generate_key()
    print(f"\nGenerated key (add to .env):\nSOCIAL_MEDIA_ENCRYPTION_KEY={new_key}")

    # Test encryption/decryption
    test_token = "test_access_token_12345"
    encrypted = encrypt_token(test_token)
    decrypted = decrypt_token(encrypted)

    print(f"\nOriginal: {test_token}")
    print(f"Encrypted: {encrypted[:50]}...")
    print(f"Decrypted: {decrypted}")
    print(f"Match: {test_token == decrypted}")
    print(f"Key source: {get_key_source()}")
