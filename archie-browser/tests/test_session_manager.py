import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet as _Fernet
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "")


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        import session_manager
        plaintext = '{"cookies": [{"name": "session", "value": "abc123"}]}'
        encrypted = session_manager._encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = session_manager._decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self):
        import session_manager
        text = "same plaintext"
        enc1 = session_manager._encrypt(text)
        enc2 = session_manager._encrypt(text)
        assert enc1 != enc2

    def test_decrypt_wrong_key_raises(self):
        import session_manager
        from cryptography.fernet import Fernet, InvalidToken
        encrypted = session_manager._encrypt("secret")
        orig = os.environ["BROWSER_ENCRYPTION_KEY"]
        os.environ["BROWSER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        session_manager._fernet_cache.clear()
        with pytest.raises((InvalidToken, Exception)):
            session_manager._decrypt(encrypted)
        os.environ["BROWSER_ENCRYPTION_KEY"] = orig
        session_manager._fernet_cache.clear()
