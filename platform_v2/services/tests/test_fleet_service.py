"""Tests for fleet_service — reads from live database."""

import sys
import os

# Ensure platform_v2 is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from services.fleet_service import (
    list_nodes,
    list_providers,
    get_node_status,
    get_usage_summary,
    get_fleet_map_data,
    HUB_LOCATION,
    PROVIDER_LOCATIONS,
)


def test_list_nodes():
    """list_nodes returns a list with expected fields."""
    nodes = list_nodes()
    assert isinstance(nodes, list)
    if nodes:
        n = nodes[0]
        for field in ["id", "node_name", "hostname", "status", "gpu_model", "ram_gb"]:
            assert field in n, f"Missing field: {field}"


def test_list_providers():
    """list_providers returns a list with provider_key and capabilities."""
    providers = list_providers()
    assert isinstance(providers, list)
    assert len(providers) > 0, "Expected at least one provider"
    p = providers[0]
    assert "provider_key" in p
    assert "capabilities" in p
    assert "is_active" in p


def test_get_usage_summary():
    """get_usage_summary returns dict with total_calls, total_cost."""
    summary = get_usage_summary()
    assert isinstance(summary, dict)
    assert "total_calls" in summary
    assert "total_cost" in summary
    assert "total_tokens" in summary
    assert "by_model" in summary
    assert isinstance(summary["by_model"], list)


def test_get_fleet_map_data():
    """get_fleet_map_data returns hub + nodes + providers arrays."""
    data = get_fleet_map_data()
    assert "hub" in data
    assert "nodes" in data
    assert "providers" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["providers"], list)
    # Hub should have coordinates
    assert data["hub"]["lat"] is not None
    assert data["hub"]["lon"] is not None


def test_get_fleet_map_data_has_coordinates():
    """Every map pin with a known location has lat/lon."""
    data = get_fleet_map_data()
    # Hub always has coords
    assert data["hub"]["lat"] == HUB_LOCATION["lat"]
    assert data["hub"]["lon"] == HUB_LOCATION["lon"]
    # Providers with known locations should have coords
    for p in data["providers"]:
        if p["provider_key"] in PROVIDER_LOCATIONS:
            assert p["lat"] is not None, f"{p['provider_key']} missing lat"
            assert p["lon"] is not None, f"{p['provider_key']} missing lon"


def test_get_node_status():
    """get_node_status by ID returns node info or None."""
    nodes = list_nodes()
    if nodes:
        node_id = nodes[0]["id"]
        status = get_node_status(node_id)
        assert status is not None
        assert status["id"] == node_id
        assert "agents" in status
        assert "agent_count" in status
        assert "loaded_model_count" in status
    # Non-existent node returns None
    result = get_node_status(-999)
    assert result is None
