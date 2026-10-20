"""Offline checks for scram_verifier.py. The authoritative proof is the PostgreSQL round trip in phase-a-rotation-runbook.md."""
import re
import unittest

from scram_verifier import verifier


class ScramVerifier(unittest.TestCase):
    def test_shape_and_fresh_salt(self):
        a, b = verifier("a" * 32), verifier("a" * 32)
        pattern = r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+"
        self.assertRegex(a, pattern)
        self.assertNotEqual(a, b)  # same password, different salt: a changed hash is observable

    def test_plaintext_never_in_output(self):
        self.assertNotIn("b" * 32, verifier("b" * 32))

    def test_rejects_unsafe_passwords_without_echoing_them(self):
        for bad in ["short", "has space " * 4, "pä" * 20, "a/b+c=" * 8]:
            with self.assertRaises(ValueError) as ctx:
                verifier(bad)
            self.assertNotIn(bad, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
