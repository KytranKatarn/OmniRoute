"""Generic retry must not bypass Repair Bay governance or worker-stop evidence."""

from copy import deepcopy
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
import pytest
from services import delegation_service as service


@pytest.mark.parametrize("status", ["blocked", "failed"])
@pytest.mark.parametrize("proposal_id", [19, None, "malformed"])
def test_generic_retry_cannot_requeue_planned_repair(status, proposal_id):
    row = {
        "id": 77,
        "status": status,
        "delegation_source": "automation",
        "delegation_args": {"capability": "codex_task", "args": {"repair_proposal_id": proposal_id}},
        "metadata": {},
    }
    before = deepcopy(row)
    cur = MagicMock()
    cur.fetchone.return_value = row

    @contextmanager
    def db(**kwargs):
        yield None, cur

    with patch.object(service, "get_db_cursor", db):
        result = service.requeue_blocked_delegation(77)
    assert result["success"] is False
    assert result["error"] == "planned_repair_recovery_required"
    assert row == before
    assert not any(
        call.args[0].lstrip().startswith(("UPDATE", "INSERT", "DELETE")) for call in cur.execute.call_args_list
    )
