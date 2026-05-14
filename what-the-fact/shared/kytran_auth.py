"""Thin shim — delegates to the pip-installed kytran-sdk package.

The canonical implementation lives in kytran_auth (installed via kytran-sdk).
This module exists so that `from shared.kytran_auth import KytranAuth` in
consumer code continues to work without modification.
"""
from kytran_auth import KytranAuth  # noqa: F401
