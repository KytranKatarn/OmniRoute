from unittest.mock import patch


class _Cursor:
    def __init__(self):
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class _Db:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return None, self.cursor

    def __exit__(self, exc_type, exc, tb):
        return False


def test_public_roster_queries_only_public_ai_agents():
    from services.public_roster_service import get_public_roster

    cursor = _Cursor()
    with patch("services.public_roster_service.get_db_cursor", return_value=_Db(cursor)):
        result = get_public_roster()

    assert result["success"] is True
    assert "FROM agents a" in cursor.sql
    assert "a.worker_type = %s" in cursor.sql
    assert "a.visibility = %s" in cursor.sql
    assert "a.shift_state <> 'decommissioned'" in cursor.sql
    assert cursor.params[:2] == ["ai", "public"]


def test_public_live_roster_filters_to_public_ai_agents():
    from services.public_roster_service import get_public_roster_live

    cursor = _Cursor()
    with patch("services.public_roster_service.get_db_cursor", return_value=_Db(cursor)):
        result = get_public_roster_live()

    assert result["success"] is True
    assert "a.worker_type = 'ai'" in cursor.sql
    assert "a.visibility = 'public'" in cursor.sql
    assert "a.shift_state != 'decommissioned'" in cursor.sql


def test_directory_snapshot_rejects_non_public_agents():
    from services.public_roster_service import validate_directory_snapshot

    assert (
        validate_directory_snapshot(
            {
                "success": True,
                "agents": [
                    {
                        "worker_type": "ai",
                        "visibility": "public",
                        "shift_state": "active",
                    }
                ],
            }
        )
        is True
    )
    assert (
        validate_directory_snapshot(
            {
                "success": True,
                "agents": [
                    {
                        "worker_type": "internal",
                        "visibility": "public",
                        "shift_state": "active",
                    }
                ],
            }
        )
        is False
    )
    assert (
        validate_directory_snapshot(
            {
                "success": True,
                "agents": [
                    {
                        "worker_type": "ai",
                        "visibility": "internal",
                        "shift_state": "active",
                    }
                ],
            }
        )
        is False
    )
    assert (
        validate_directory_snapshot(
            {
                "success": True,
                "agents": [
                    {
                        "worker_type": "ai",
                        "visibility": "public",
                        "shift_state": "active",
                        "email": "private@example.com",
                    }
                ],
            }
        )
        is False
    )


def test_directory_snapshot_writer_fails_closed_for_invalid_roster():
    from services.public_roster_service import write_directory_snapshot

    with patch(
        "services.public_roster_service.get_public_roster",
        return_value={"success": True, "agents": []},
    ):
        assert write_directory_snapshot() is False
