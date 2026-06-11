"""Validation tests for browser_platform_service (#4006).

Pure-logic tests — no DB. The registry CRUD is exercised live; what must
never regress silently is the validation matrix, because it gates what a
headed browser inside the owner's trusted profile may navigate to.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.browser_platform_service import (  # noqa: E402
    PLATFORM_RE,
    valid_public_host,
    validate_platform_payload,
)


class TestValidPublicHost:
    def test_accepts_public_fqdn(self):
        assert valid_public_host("www.linkedin.com")
        assert valid_public_host("chat.deepseek.com")
        assert valid_public_host("sub.domain.co.uk")

    def test_normalizes_case_and_trailing_dot(self):
        assert valid_public_host("WWW.LinkedIn.COM")
        assert valid_public_host("example.com.")

    def test_rejects_ip_literals(self):
        assert not valid_public_host("192.168.1.200")
        assert not valid_public_host("100.64.0.4")
        assert not valid_public_host("::1")
        assert not valid_public_host("2001:db8::1")

    def test_rejects_single_label_docker_names(self):
        # A single-label name would resolve to a compose service —
        # archie_database, ollama, etc.
        assert not valid_public_host("archie_database")
        assert not valid_public_host("localhost")
        assert not valid_public_host("ollama")

    def test_rejects_internal_suffixes(self):
        assert not valid_public_host("printer.local")
        assert not valid_public_host("vault.internal")
        assert not valid_public_host("nas.lan")

    def test_rejects_garbage(self):
        assert not valid_public_host("")
        assert not valid_public_host(None)
        assert not valid_public_host("-bad.example.com")
        assert not valid_public_host("exa mple.com")
        assert not valid_public_host("a." * 200 + "com")


class TestPlatformKey:
    def test_key_shape(self):
        assert PLATFORM_RE.match("linkedin")
        assert PLATFORM_RE.match("my_site-2")
        assert not PLATFORM_RE.match("x")  # too short
        assert not PLATFORM_RE.match("Has Caps")
        assert not PLATFORM_RE.match("dots.not.allowed")
        assert not PLATFORM_RE.match("a" * 33)  # too long


class TestValidatePlatformPayload:
    HOSTS = ["www.example.com", "example.com"]

    def test_valid_minimal(self):
        assert validate_platform_payload("mysite", "My Site", self.HOSTS) is None

    def test_valid_with_urls(self):
        assert (
            validate_platform_payload(
                "mysite",
                "My Site",
                self.HOSTS,
                login_url="https://www.example.com/login",
                probe_url="https://example.com/me",
            )
            is None
        )

    def test_rejects_bad_key(self):
        assert validate_platform_payload("Bad Key", "My Site", self.HOSTS)

    def test_rejects_missing_display_name(self):
        assert validate_platform_payload("mysite", "", self.HOSTS)

    def test_rejects_empty_hosts(self):
        assert validate_platform_payload("mysite", "My Site", [])
        assert validate_platform_payload("mysite", "My Site", "not-a-list")

    def test_rejects_private_host_in_list(self):
        assert validate_platform_payload("mysite", "My Site", ["example.com", "192.168.1.200"])

    def test_rejects_http_login_url(self):
        assert validate_platform_payload("mysite", "My Site", self.HOSTS, login_url="http://www.example.com/login")

    def test_rejects_login_url_host_outside_allowlist(self):
        assert validate_platform_payload("mysite", "My Site", self.HOSTS, login_url="https://evil.com/login")

    def test_rejects_bad_probe_url(self):
        assert validate_platform_payload("mysite", "My Site", self.HOSTS, probe_url="https://other.com/me")
