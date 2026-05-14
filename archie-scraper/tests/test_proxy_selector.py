import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proxy_selector import select_egress


def test_gc_ca_routes_to_tier1():
    assert select_egress("https://canadabuys.canada.ca/en/tenders") == 1


def test_canada_ca_routes_to_tier1():
    assert select_egress("https://open.canada.ca/data") == 1


def test_explicit_tier_overrides_domain():
    assert select_egress("https://canadabuys.canada.ca/tenders", requested_tier=2) == 2


def test_unknown_domain_defaults_to_tier1():
    assert select_egress("https://httpbin.org/get") == 1


def test_gouv_qc_routes_to_tier1():
    assert select_egress("https://seao.ca/openweb/index.do") == 1
