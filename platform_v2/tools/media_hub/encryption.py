"""
Media Hub Token Encryption
==========================
Fernet-based encryption for API keys.

Uses the MEDIA_HUB_ENCRYPTION_KEY environment variable.
If not set, generates a key on first use and logs a warning.

Usage:
    from tools.media_hub.encryption import encrypt_api_key, decrypt_api_key

    # Encrypt before storing
    encrypted = encrypt_api_key("my_api_key")

    # Decrypt when needed
    original = decrypt_api_key(encrypted)
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
    key = os.getenv("MEDIA_HUB_ENCRYPTION_KEY")

    if key:
        _key_source = "environment"
        try:
            _fernet = Fernet(key.encode() if isinstance(key, str) else key)
            logger.info("Media Hub encryption initialized from environment key")
        except Exception as e:
            logger.error(f"Invalid encryption key in environment: {e}")
            raise ValueError(
                "MEDIA_HUB_ENCRYPTION_KEY is invalid. Generate new key with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
    else:
        # Generate a key for development (NOT RECOMMENDED FOR PRODUCTION)
        _key_source = "generated"
        _fernet = Fernet(Fernet.generate_key())
        logger.warning(
            "MEDIA_HUB_ENCRYPTION_KEY not set! "
            "Using generated key - API keys will be lost on restart. "
            "Generate a permanent key with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    return _fernet


def encrypt_api_key(plaintext: str) -> str:
    """
    Encrypt an API key string.

    Args:
        plaintext: The API key to encrypt

    Returns:
        Base64-encoded encrypted string (safe for database storage)
    """
    if not plaintext:
        return None

    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_api_key(encrypted: str) -> str:
    """
    Decrypt an encrypted API key.

    Args:
        encrypted: Base64-encoded encrypted string from database

    Returns:
        Original plaintext API key

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
        logger.error("Failed to decrypt API key - key may have changed")
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
    print("Testing Media Hub encryption module...")

    # Generate and display a new key
    new_key = generate_key()
    print(f"\nGenerated key (add to .env):\nMEDIA_HUB_ENCRYPTION_KEY={new_key}")

    # Test encryption/decryption
    test_key = "test_api_key_12345"
    encrypted = encrypt_api_key(test_key)
    decrypted = decrypt_api_key(encrypted)

    print(f"\nOriginal: {test_key}")
    print(f"Encrypted: {encrypted[:50]}...")
    print(f"Decrypted: {decrypted}")
    print(f"Match: {test_key == decrypted}")
    print(f"Key source: {get_key_source()}")
