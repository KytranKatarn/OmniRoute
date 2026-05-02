# tests/test_skill_fleet_push_port.py
"""Regression guard: push_skills_to_fleet must use node_api_port from DB."""
import os


def _read_push_func() -> str:
    jobs_path = os.path.join(
        os.path.dirname(__file__),
        "..", "platform_v2", "tools", "consciousness", "jobs.py",
    )
    with open(jobs_path) as f:
        source = f.read()
    start = source.find("def push_skills_to_fleet(")
    end = source.find("\ndef ", start + 1)
    return source[start:end]


def test_no_hardcoded_9091():
    func = _read_push_func()
    assert "9091" not in func, (
        "Port 9091 is hardcoded in push_skills_to_fleet — must use node['node_api_port']"
    )


def test_reads_node_api_port_from_node_dict():
    func = _read_push_func()
    assert "node_api_port" in func, (
        "push_skills_to_fleet must read node_api_port from the node record"
    )


def test_select_includes_node_api_port():
    func = _read_push_func()
    select_block = func[func.find("SELECT id"):func.find("inbound_port")]
    assert "node_api_port" in select_block, (
        "The SELECT query for remote_nodes must include the node_api_port column"
    )
