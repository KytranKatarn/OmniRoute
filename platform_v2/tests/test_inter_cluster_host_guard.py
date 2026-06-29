"""Task #4552 (hub-side) — _valid_inter_cluster_host rejects values that can
never be valid inter-cluster addresses, so they can't poison
remote_nodes.hostname (e.g. the docker-bridge 172.27.0.1 on outpost-us).

It must KEEP legit values: Starship LAN 192.168.x, mesh 100.64.x, public IPs,
and non-IP hostnames like host.docker.internal.
"""

from tools.department_hq.fleet_node_routes import _valid_inter_cluster_host


def test_rejects_docker_bridge_gateways():
    # 172.16.0.0/12 — docker default network range (the outpost-us bug)
    for v in ("172.27.0.1", "172.16.0.1", "172.17.0.1", "172.31.255.254"):
        assert _valid_inter_cluster_host(v) is None, v


def test_rejects_loopback_linklocal_unspecified():
    for v in ("127.0.0.1", "127.1.2.3", "169.254.1.1", "0.0.0.0"):
        assert _valid_inter_cluster_host(v) is None, v


def test_rejects_docker_container_short_id():
    assert _valid_inter_cluster_host("a1b2c3d4e5f6") is None
    assert _valid_inter_cluster_host("0123456789ab") is None


def test_rejects_empty_and_none():
    assert _valid_inter_cluster_host(None) is None
    assert _valid_inter_cluster_host("") is None


def test_allows_starship_lan_ip():
    # Starships legitimately report their LAN IP — must NOT be rejected
    assert _valid_inter_cluster_host("192.168.1.246") == "192.168.1.246"
    assert _valid_inter_cluster_host("192.168.1.245") == "192.168.1.245"


def test_allows_mesh_ip():
    assert _valid_inter_cluster_host("100.64.0.2") == "100.64.0.2"


def test_allows_public_ip():
    # outpost-us public IP (the value #4552's deferred half will set) + others
    for v in ("76.13.107.109", "2.25.133.122", "156.67.217.86"):
        assert _valid_inter_cluster_host(v) == v


def test_allows_hostname_strings():
    # non-IP strings (the hub's host.docker.internal) pass through
    assert _valid_inter_cluster_host("host.docker.internal") == "host.docker.internal"
    assert _valid_inter_cluster_host("archie-starbase") == "archie-starbase"
