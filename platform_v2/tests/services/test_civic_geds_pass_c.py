import base64
import pytest
from unittest.mock import AsyncMock, MagicMock
from services.civic_geds_pass_c import enrich_quick_lists

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def b64(s: str) -> str:
    return base64.b64encode(s.encode("ascii")).decode("ascii")


async def test_enrich_quick_lists_tags_each_role():
    min_dn = b64("OU=Minister1,OU=DEPT,O=GC,C=CA")
    dm_dn = b64("OU=DM1,OU=DEPT,O=GC,C=CA")
    sen_dn = b64("OU=Sen1,OU=DEPT,O=GC,C=CA")
    mp_dn = b64("OU=MP1,OU=DEPT,O=GC,C=CA")

    pages = {
        "?pgid=016&fid=10": f'<a href="?pgid=015&dn={min_dn}">Min, A.</a>',
        "?pgid=016&fid=11": f'<a href="?pgid=015&dn={dm_dn}">DM, B.</a>',
        "?pgid=016&fid=12": f'<a href="?pgid=015&dn={sen_dn}">Sen, C.</a>',
        "?pgid=016&fid=13": f'<a href="?pgid=015&dn={mp_dn}">MP, D.</a>',
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    # Each UPDATE returns a row (existing employee found)
    fake_cur.fetchone.return_value = (1,)

    counts = await enrich_quick_lists(client, fake_conn)
    assert counts["minister"] == 1
    assert counts["deputy_minister"] == 1
    assert counts["senator"] == 1
    assert counts["mp"] == 1

    # 4 UPDATE calls (one per row, each found existing)
    update_calls = [
        c for c in fake_cur.execute.call_args_list if "UPDATE" in c.args[0].upper() and "federal_employees" in c.args[0]
    ]
    assert len(update_calls) == 4
    fake_conn.commit.assert_called_once()


async def test_enrich_falls_back_to_synthetic_org_for_unmatched_person():
    mp_dn = b64("OU=MP1,OU=DEPT,O=GC,C=CA")

    pages = {
        "?pgid=016&fid=10": "",
        "?pgid=016&fid=11": "",
        "?pgid=016&fid=12": "",
        "?pgid=016&fid=13": f'<a href="?pgid=015&dn={mp_dn}">MP, D.</a>',
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur

    # First UPDATE returns None (no existing row); fallback path opens a NEW cursor for org_unit insert
    # then a NEW cursor for the employee insert. Use side_effect on fetchone:
    fake_cur.fetchone.side_effect = [
        None,  # UPDATE federal_employees ... RETURNING id -> not found
        (99,),  # INSERT INTO org_units ... RETURNING id -> synthetic org id
    ]

    counts = await enrich_quick_lists(client, fake_conn)
    assert counts["mp"] == 1

    # Verify a synthetic org_unit insert happened
    org_inserts = [
        c for c in fake_cur.execute.call_args_list if "org_units" in c.args[0] and "INSERT" in c.args[0].upper()
    ]
    assert len(org_inserts) >= 1
    # Verify a federal_employees insert happened (the fallback)
    emp_inserts = [
        c for c in fake_cur.execute.call_args_list if "federal_employees" in c.args[0] and "INSERT" in c.args[0].upper()
    ]
    assert len(emp_inserts) >= 1


async def test_enrich_handles_fid_fetch_failure():
    from services.civic_geds_client import GedsFetchError

    dm_dn = b64("OU=DM1,OU=DEPT,O=GC,C=CA")

    async def get(p):
        if p == "?pgid=016&fid=10":
            raise GedsFetchError("simulated 503")
        if p == "?pgid=016&fid=11":
            return f'<a href="?pgid=015&dn={dm_dn}">DM, B.</a>'
        return ""

    client = AsyncMock()
    client.get.side_effect = get

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    fake_cur.fetchone.return_value = (1,)

    counts = await enrich_quick_lists(client, fake_conn)
    assert counts["minister"] == 0
    assert counts["deputy_minister"] == 1
    assert counts["senator"] == 0
    assert counts["mp"] == 0
