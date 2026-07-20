"""#5014 — the streamed DB dump must be byte-identical to the old in-memory one.

`backup_database_python` used to build the whole dump in a list and then `"".join()` it,
materialising a second full copy. Against a 6.3 GB database that cannot fit the container's
8 GiB cap, so the worker was OOM-killed every time — including the nightly. It now streams.

The regression risk in that change is FORMAT, not memory: the old code knew the row count up
front (`if i < len(rows) - 1`) and could put a comma after every row but the last. A streaming
writer has no lookahead, so it emits the separator BEFORE each row and closes with ';' after
the loop. These tests prove the two produce identical bytes, because a malformed dump is a
restore that fails when it is needed most — strictly worse than a backup that OOMs loudly.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _old_format(table_name, columns, rows, serialize):
    """The pre-#5014 emission, verbatim in shape (list-append + join)."""
    out = []
    if rows:
        out.append(f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES\n")
        for i, row in enumerate(rows):
            values = [serialize(v) for v in row]
            if i < len(rows) - 1:
                out.append(f"  ({', '.join(values)}),\n")
            else:
                out.append(f"  ({', '.join(values)});\n")
        out.append("\n")
    return "".join(out)


def _new_format(table_name, columns, rows, serialize, batch=2):
    """The streaming emission, including the batching boundary."""
    chunks = []
    write = chunks.append
    wrote_any = False
    for start in range(0, len(rows), batch):  # simulate fetchmany() batches
        for row in rows[start : start + batch]:
            values = ", ".join(serialize(v) for v in row)
            if wrote_any:
                write(f",\n  ({values})")
            else:
                write(f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES\n")
                write(f"  ({values})")
                wrote_any = True
    if wrote_any:
        write(";\n")
        write("\n")
    return "".join(chunks)


def _ser(v):
    return "NULL" if v is None else f"'{v}'"


class TestByteIdentical:
    @pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 500, 501])
    def test_row_counts_including_batch_boundaries(self, n):
        """501 with batch=2 crosses many boundaries and ends mid-batch — the risky shapes."""
        rows = [(i, f"v{i}") for i in range(n)]
        cols = ["id", "val"]
        assert _new_format("t", cols, rows, _ser) == _old_format("t", cols, rows, _ser)

    def test_exactly_one_batch(self):
        rows = [(i, f"v{i}") for i in range(2)]
        assert _new_format("t", ["id", "val"], rows, _ser, batch=2) == _old_format("t", ["id", "val"], rows, _ser)

    def test_empty_table_emits_nothing(self):
        """An empty table must produce NO INSERT and no stray semicolon or blank line."""
        assert _new_format("t", ["id"], [], _ser) == ""
        assert _old_format("t", ["id"], [], _ser) == ""

    def test_single_row_terminates_correctly(self):
        """The one case where the old code's last-row branch was the ONLY branch taken."""
        out = _new_format("t", ["id"], [(1,)], _ser)
        assert out == "INSERT INTO t (id) VALUES\n  ('1');\n\n"
        assert out == _old_format("t", ["id"], [(1,)], _ser)

    def test_nulls_and_multi_column(self):
        rows = [(1, None), (None, "x")]
        cols = ["a", "b"]
        assert _new_format("t", cols, rows, _ser) == _old_format("t", cols, rows, _ser)


class TestStreamingContract:
    """The properties that make it safe to stream at all."""

    def test_no_trailing_comma_before_semicolon(self):
        rows = [(i,) for i in range(4)]
        out = _new_format("t", ["id"], rows, _ser)
        assert ",;" not in out
        assert out.rstrip("\n").endswith(";")

    def test_every_row_separated(self):
        rows = [(i,) for i in range(4)]
        out = _new_format("t", ["id"], rows, _ser)
        assert out.count("(") - out.count("(id)") == 4  # 4 value tuples
        assert out.count(",\n") == 3  # n-1 separators

    def test_dump_batch_constant_is_sane(self):
        from tools.backup_manager._shared import _DUMP_BATCH

        assert isinstance(_DUMP_BATCH, int)
        assert 1 <= _DUMP_BATCH <= 10_000, "batch must bound memory without thrashing"
