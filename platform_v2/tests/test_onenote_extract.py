"""Unit tests for the Mailbox Story OneNote (.one) extraction engine (no DB, no network).

clean_runs / _chunk / file_kind / extract_one_text are pure or file-based, so they run anywhere.
The DB-writing extract_onenote is exercised live during deploy verification, not here.
"""

import os
import tempfile

import services.onenote_extract_service as svc


# ---------- file_kind (content sniff) ----------


def _tmp(data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".one")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def test_file_kind_pst():
    p = _tmp(b"!BDN" + b"\x00" * 32)
    try:
        assert svc.file_kind(p) == "pst"
    finally:
        os.unlink(p)


def test_file_kind_onenote():
    p = _tmp(svc.ONENOTE_MAGIC + b"\x00" * 32)
    try:
        assert svc.file_kind(p) == "onenote"
    finally:
        os.unlink(p)


def test_file_kind_unknown():
    p = _tmp(b"random junk bytes not a known format")
    try:
        assert svc.file_kind(p) == "unknown"
    finally:
        os.unlink(p)


# ---------- clean_runs (decode-noise -> readable runs) ----------


def test_clean_runs_keeps_prose_and_email_drops_noise():
    runs = svc.clean_runs(
        "The procurement consultation process was completed on time.\n"
        "From: Jane Auditor <jane.auditor@tpsgc-pwgsc.gc.ca>\n"
        "xmlns:one=http://schemas.microsoft.com/office/onenote\n"
        "Calibri\n"
        "7B5C52E4D88C4DA7AEB15378D02996D3\n"
    )
    joined = "\n".join(runs)
    assert "procurement consultation process" in joined
    assert "jane.auditor@tpsgc-pwgsc.gc.ca" in joined
    assert "xmlns" not in joined  # schema noise dropped
    assert "Calibri" not in joined  # font noise dropped
    assert "7B5C52E4D88C" not in joined  # bare GUID dropped


def test_clean_runs_dedups_consecutive():
    runs = svc.clean_runs("Caetano, Terry repeated line here\nCaetano, Terry repeated line here\n")
    assert len(runs) == 1


def test_clean_runs_drops_guid_pseudo_address_keeps_real():
    runs = svc.clean_runs("042911d2c977494d846ab1c8edc55646@tpsgc-pwgsc.gc.ca\n" "jane.auditor@tpsgc-pwgsc.gc.ca\n")
    joined = "\n".join(runs)
    assert "042911d2c977494d846ab1c8edc55646@" not in joined  # OneNote object-id, not a contact
    assert "jane.auditor@tpsgc-pwgsc.gc.ca" in joined  # real address preserved


# ---------- _chunk (size-based page splitting) ----------


def test_chunk_splits_on_size():
    runs = ["x" * 2000 for _ in range(10)]  # 10 runs * 2000 chars
    chunks = svc._chunk(runs)
    assert len(chunks) > 1
    assert all(len(c) <= svc._CHUNK_CHARS + 2100 for c in chunks)  # never wildly over a page


def test_chunk_single_when_small():
    assert svc._chunk(["a short note about the SPAC workplace process"]) == [
        "a short note about the SPAC workplace process"
    ]


# ---------- extract_one_text (UTF-16LE decode of a synthetic .one) ----------


def test_extract_one_text_recovers_utf16_prose():
    text = "Project Northstar milestone achieved on schedule by the SPAC team."
    blob = svc.ONENOTE_MAGIC + b"\x01\x02\x03" + text.encode("utf-16-le") + b"\x00\x00"
    p = _tmp(blob)
    try:
        runs = svc.extract_one_text(p)
    finally:
        os.unlink(p)
    assert any("Project Northstar milestone achieved" in r for r in runs)


def test_extract_one_text_accented_french():
    text = "Réalisation du processus et résolution des enjeux avec SPC à Gatineau."
    blob = svc.ONENOTE_MAGIC + text.encode("utf-16-le")
    p = _tmp(blob)
    try:
        runs = svc.extract_one_text(p)
    finally:
        os.unlink(p)
    joined = "\n".join(runs)
    assert "Réalisation" in joined and "résolution" in joined  # accents preserved (not strings-split)


# ---------- _safe_extractall (Zip Slip defense) ----------


def test_safe_extractall_blocks_path_traversal():
    import zipfile

    tmp = tempfile.mkdtemp()
    zpath = os.path.join(tmp, "evil.zip")
    dest = os.path.join(tmp, "dest")
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../escaped.one", "x")  # traversal attempt
        zf.writestr("inside/good.one", "y")  # legit
    svc._safe_extractall(zpath, dest)
    # the traversal member must NOT have escaped dest
    assert not os.path.exists(os.path.join(tmp, "escaped.one"))
    # the safe member is extracted
    assert os.path.exists(os.path.join(dest, "inside", "good.one"))


def test_safe_extractall_absolute_path_blocked():
    import zipfile

    tmp = tempfile.mkdtemp()
    zpath = os.path.join(tmp, "abs.zip")
    dest = os.path.join(tmp, "dest")
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("ok.one", "z")
    svc._safe_extractall(zpath, dest)
    assert os.path.exists(os.path.join(dest, "ok.one"))
