"""Compute a PostgreSQL SCRAM-SHA-256 verifier from a password read on STDIN (never argv).

Why: `ALTER ROLE ... PASSWORD 'plaintext'` is written to the server log verbatim when log_statement covers DDL, and
shows up in `ps`/shell history if passed as an argument. Sending the verifier instead means the plaintext never
reaches the server or its logs. The verifier cannot be used to log in without the password.

    printf '%s' "$PW" | python3 scram_verifier.py          # prints the verifier only
Restricted to ASCII letters/digits (e.g. `openssl rand -hex 24`): SASLprep is the identity for those, so no
normalisation library is needed and the result matches what the server computes.
"""
import base64
import hashlib
import hmac
import os
import re
import sys


def verifier(password: str, iterations: int = 4096, salt: bytes | None = None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{16,128}", password):
        raise ValueError("password must be 16-128 ASCII letters/digits (use openssl rand -hex 24)")
    salt = salt if salt is not None else os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


if __name__ == "__main__":
    try:
        print(verifier(sys.stdin.readline().rstrip("\n")))
    except ValueError as exc:
        sys.exit(f"refused: {exc}")  # never echo the input
