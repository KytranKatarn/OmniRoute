import base64
import pytest
from unittest.mock import AsyncMock
from services.civic_geds_pass_b import sweep_people, EmployeeWriter

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def b64(s: str) -> str:
    return base64.b64encode(s.encode("ascii")).decode("ascii")


async def test_sweep_people_writes_one_per_unique_dn():
    leaf1_b64 = b64("OU=LEAF1,O=GC,C=CA")
    leaf2_b64 = b64("OU=LEAF2,O=GC,C=CA")
    person_a = b64("OU=Smith,OU=LEAF1,O=GC,C=CA")
    person_b = b64("OU=Lee,OU=LEAF2,O=GC,C=CA")

    pages = {
        f"?pgid=014&dn={leaf1_b64}": (
            f"<main>"
            f'<li><a href="?pgid=015&dn={person_a}">Smith, John</a>'
            f"<dl><dt>Title</dt><dd>Director General</dd>"
            f"<dt>Classification</dt><dd>EX-03</dd></dl></li>"
            f"</main>"
        ),
        f"?pgid=014&dn={leaf2_b64}": (
            f"<main>"
            f'<li><a href="?pgid=015&dn={person_b}">Lee, Sarah</a>'
            f"<dl><dt>Title</dt><dd>Senior Analyst</dd></dl></li>"
            f"</main>"
        ),
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    leaf_units = [
        {"id": 1, "dn_b64": leaf1_b64},
        {"id": 2, "dn_b64": leaf2_b64},
    ]
    written = []

    class FakeWriter(EmployeeWriter):
        def __init__(self):
            pass

        def upsert(self, **row):
            written.append(row)

        def commit(self):
            pass

    n = await sweep_people(client, leaf_units, FakeWriter())
    assert n == 2
    surnames = {r["surname"] for r in written}
    assert surnames == {"Smith", "Lee"}
    smith = next(r for r in written if r["surname"] == "Smith")
    assert smith["title_en"] == "Director General"
    assert smith["classification"] == "EX-03"
    assert smith["org_unit_id"] == 1


async def test_sweep_people_dedupes_within_run():
    leaf1_b64 = b64("OU=LEAF1,O=GC,C=CA")
    leaf2_b64 = b64("OU=LEAF2,O=GC,C=CA")
    same_person = b64("OU=Adams,OU=BOTH,O=GC,C=CA")

    pages = {
        f"?pgid=014&dn={leaf1_b64}": (f'<main><li><a href="?pgid=015&dn={same_person}">Adams, Bob</a></li></main>'),
        f"?pgid=014&dn={leaf2_b64}": (f'<main><li><a href="?pgid=015&dn={same_person}">Adams, Bob</a></li></main>'),
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    leaf_units = [
        {"id": 1, "dn_b64": leaf1_b64},
        {"id": 2, "dn_b64": leaf2_b64},
    ]
    written = []

    class FakeWriter(EmployeeWriter):
        def __init__(self):
            pass

        def upsert(self, **row):
            written.append(row)

        def commit(self):
            pass

    n = await sweep_people(client, leaf_units, FakeWriter())
    assert n == 1, f"expected 1 dedup'd person, got {n}"


async def test_sweep_handles_fetch_failure_for_one_leaf():
    from services.civic_geds_client import GedsFetchError

    ok_b64 = b64("OU=OK,O=GC,C=CA")
    bad_b64 = b64("OU=BAD,O=GC,C=CA")
    person = b64("OU=Worker,OU=OK,O=GC,C=CA")

    pages = {
        f"?pgid=014&dn={ok_b64}": (f'<main><li><a href="?pgid=015&dn={person}">Worker, A.</a></li></main>'),
    }
    client = AsyncMock()

    async def get(p):
        if p in pages:
            return pages[p]
        raise GedsFetchError("simulated 503")

    client.get.side_effect = get

    leaf_units = [
        {"id": 1, "dn_b64": ok_b64},
        {"id": 2, "dn_b64": bad_b64},
    ]
    written = []

    class FakeWriter(EmployeeWriter):
        def __init__(self):
            pass

        def upsert(self, **row):
            written.append(row)

        def commit(self):
            pass

    n = await sweep_people(client, leaf_units, FakeWriter())
    assert n == 1
