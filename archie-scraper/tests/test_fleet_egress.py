import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch


def test_discover_fleet_egress_returns_online_nodes():
    from proxy_selector import discover_fleet_egress

    mock_rows = [
        {"node_name": "node_245", "mesh_ip": "100.64.0.3"},
        {"node_name": "node_246", "mesh_ip": "100.64.0.4"},
    ]

    with patch("proxy_selector.get_db") as mock_db:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = mock_rows
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_db.return_value.__enter__ = lambda s: mock_conn
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        result = discover_fleet_egress()

    assert len(result) == 2
    assert result[0]["tier"] == 4
    assert result[0]["proxy"] == "socks5://100.64.0.3:1080"
    assert result[0]["label"] == "node_245"


def test_discover_fleet_egress_returns_empty_on_db_error():
    from proxy_selector import discover_fleet_egress

    with patch("proxy_selector.get_db", side_effect=Exception("DB down")):
        result = discover_fleet_egress()

    assert result == []
