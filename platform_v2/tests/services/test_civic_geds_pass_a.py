"""
Pass A tests — recursive org tree walk.

DN values must be real base64 of valid LDAP DNs; decode_dn will raise
DnParseError on bad b64 and production code skips those rows.

Base64 references (python: base64.b64encode(b"<dn>").decode()):
  OU=FOO-DEPT,O=GC,C=CA                        -> T1U9Rk9PLURFUFQsTz1HQyxDPUNB
  OU=BRANCH-A,OU=FOO-DEPT,O=GC,C=CA            -> T1U9QlJBTkNILUEsT1U9Rk9PLURFUFQsTz1HQyxDPUNB
  OU=BRANCH-B,OU=FOO-DEPT,O=GC,C=CA            -> T1U9QlJBTkNILUIsT1U9Rk9PLURFUFQsTz1HQyxDPUNB
  OU=BAD-DEPT,O=GC,C=CA                        -> T1U9QkFELURFUFQsTz1HQyxDPUNB
"""

import pytest
from unittest.mock import AsyncMock

from services.civic_geds_pass_a import walk_org_tree, OrgUnitWriter

pytestmark = pytest.mark.anyio

# Real base64 DNs
B64_FOO = "T1U9Rk9PLURFUFQsTz1HQyxDPUNB"
B64_A = "T1U9QlJBTkNILUEsT1U9Rk9PLURFUFQsTz1HQyxDPUNB"
B64_B = "T1U9QlJBTkNILUIsT1U9Rk9PLURFUFQsTz1HQyxDPUNB"
B64_X = "T1U9QkFELURFUFQsTz1HQyxDPUNB"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeWriter(OrgUnitWriter):
    """In-memory writer for tests."""

    def __init__(self):
        self._rows = []

    def upsert(self, **row):
        self._rows.append(row)
        return len(self._rows)

    def commit(self):
        pass

    @property
    def written(self):
        return self._rows


async def test_walk_org_tree_records_root_and_children():
    pages = {
        "?pgid=012": (f"<html><body>" f'<a href="?pgid=014&dn={B64_FOO}">Foo Dept</a>' f"</body></html>"),
        f"?pgid=014&dn={B64_FOO}": (
            f"<html><body><main>"
            f'<a href="?pgid=014&dn={B64_A}">Branch A</a>'
            f'<a href="?pgid=014&dn={B64_B}">Branch B</a>'
            f"</main></body></html>"
        ),
        f"?pgid=014&dn={B64_A}": "<html><body><main></main></body></html>",
        f"?pgid=014&dn={B64_B}": "<html><body><main></main></body></html>",
    }

    client = AsyncMock()
    client.get.side_effect = lambda path: pages[path]

    writer = FakeWriter()
    n = await walk_org_tree(client, writer, max_depth=3)

    assert n == 3
    names = [r["name_en"] for r in writer.written]
    assert "Foo Dept" in names
    assert "Branch A" in names
    assert "Branch B" in names

    levels = {r["name_en"]: r["level"] for r in writer.written}
    assert levels["Foo Dept"] == 0
    assert levels["Branch A"] == 1
    assert levels["Branch B"] == 1


async def test_walk_org_tree_parent_id_chained():
    """Children must reference parent's returned id."""
    pages = {
        "?pgid=012": f'<a href="?pgid=014&dn={B64_FOO}">Foo Dept</a>',
        f"?pgid=014&dn={B64_FOO}": (f'<main><a href="?pgid=014&dn={B64_A}">Branch A</a></main>'),
        f"?pgid=014&dn={B64_A}": "<main></main>",
    }
    client = AsyncMock()
    client.get.side_effect = lambda path: pages[path]

    writer = FakeWriter()
    await walk_org_tree(client, writer, max_depth=3)

    rows = {r["name_en"]: r for r in writer.written}
    # Root has no parent
    assert rows["Foo Dept"]["parent_id"] is None
    # Child's parent_id must equal the row id returned for Foo Dept (= 1)
    assert rows["Branch A"]["parent_id"] == 1


async def test_walk_handles_fetch_failure_gracefully():
    """If fetching a dept's tree page fails, still write the root row."""
    from services.civic_geds_client import GedsFetchError

    pages = {
        "?pgid=012": f'<a href="?pgid=014&dn={B64_X}">Bad Dept</a>',
    }

    async def get(p):
        if p == "?pgid=012":
            return pages[p]
        raise GedsFetchError("simulated 503")

    client = AsyncMock()
    client.get.side_effect = get

    writer = FakeWriter()
    n = await walk_org_tree(client, writer, max_depth=3)

    # Pass writes the root dept even if its tree fetch fails
    assert n == 1
    assert writer.written[0]["name_en"] == "Bad Dept"


async def test_walk_respects_max_depth():
    """Nodes beyond max_depth are not fetched or written."""
    # depth=0: Foo Dept (root)
    # depth=1: Branch A (child)
    # depth=2: Leaf (grandchild) — should NOT be written at max_depth=1
    B64_LEAF = "T1U9TEVBRixPVT1CUkFOQ0gtQSxPVT1GT08tREVQVCxPPUdDLEM9Q0E="  # OU=LEAF,...
    import base64

    B64_LEAF = base64.b64encode(b"OU=LEAF,OU=BRANCH-A,OU=FOO-DEPT,O=GC,C=CA").decode()

    pages = {
        "?pgid=012": f'<a href="?pgid=014&dn={B64_FOO}">Foo Dept</a>',
        f"?pgid=014&dn={B64_FOO}": (f'<main><a href="?pgid=014&dn={B64_A}">Branch A</a></main>'),
        f"?pgid=014&dn={B64_A}": (f'<main><a href="?pgid=014&dn={B64_LEAF}">Leaf</a></main>'),
        f"?pgid=014&dn={B64_LEAF}": "<main></main>",
    }
    client = AsyncMock()
    client.get.side_effect = lambda path: pages[path]

    writer = FakeWriter()
    n = await walk_org_tree(client, writer, max_depth=1)

    # max_depth=1: root (level 0) + Branch A (level 1) = 2; Leaf (level 2) skipped
    assert n == 2
    names = [r["name_en"] for r in writer.written]
    assert "Foo Dept" in names
    assert "Branch A" in names
    assert "Leaf" not in names
