"""Tests for chronicle_attachment_service (slice 03) — hermetic, no live DB rows.

Covers extract_text_from_file() for txt/docx/image-OCR/unknown-binary, and
extract_attachment()'s row-update logic via a monkeypatched DB cursor.
"""

import pytest

from services import chronicle_attachment_service as svc


# ---------------------------------------------------------------------------
# extract_text_from_file() — real fixtures, no DB involved
# ---------------------------------------------------------------------------


def test_extract_txt(tmp_path):
    content = "Hello from a plain text Chronicle attachment.\nSecond line."
    p = tmp_path / "note.txt"
    p.write_text(content, encoding="utf-8")

    text, ocr_used = svc.extract_text_from_file(str(p), "text/plain")

    assert text == content
    assert ocr_used is False


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    p = tmp_path / "letter.docx"
    d = docx.Document()
    d.add_paragraph("Hello Terry from a docx")
    d.save(str(p))

    text, ocr_used = svc.extract_text_from_file(
        str(p),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert "Hello Terry" in text
    assert ocr_used is False


def test_extract_image_ocr(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    ImageFont = pytest.importorskip("PIL.ImageFont")

    img = Image.new("RGB", (800, 200), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:
        # Older Pillow's load_default() has no `size` kwarg.
        font = ImageFont.load_default()
    draw.text((20, 50), "CHRONICLE", fill="black", font=font)

    p = tmp_path / "scan.png"
    img.save(str(p))

    text, ocr_used = svc.extract_text_from_file(str(p), "image/png")

    assert "chronicle" in text.lower()
    assert ocr_used is True


def test_unknown_type_returns_empty(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01\x02\xff\xfe")

    text, ocr_used = svc.extract_text_from_file(str(p), "application/octet-stream")

    assert text == ""
    assert ocr_used is False


# ---------------------------------------------------------------------------
# extract_attachment() — DB interaction, monkeypatched
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal cursor recording executed statements + params, with a canned
    fetchone() result."""

    def __init__(self, fetchone_result=None):
        self._fetchone_result = fetchone_result
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return []


class _FakeCursorCtx:
    """Context manager mimicking `with get_db_cursor(commit=...) as (conn, cur):`
    Shares one cursor instance across all `with` blocks so assertions can
    inspect everything that was executed."""

    def __init__(self, cursor):
        self._cursor = cursor

    def __call__(self, commit=True):
        return self

    def __enter__(self):
        return (None, self._cursor)

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_extract_attachment_marks_error_on_missing_file(monkeypatch):
    fake_cursor = _FakeCursor(
        fetchone_result={"stored_path": "/tmp/does-not-exist-chronicle.pdf", "mime_type": "application/pdf"}
    )
    fake_ctx = _FakeCursorCtx(fake_cursor)
    monkeypatch.setattr("database.get_db_cursor", fake_ctx)

    status = svc.extract_attachment(42)

    assert status == "error"
    # Second statement executed should be the error UPDATE.
    update_sql, update_params = fake_cursor.executed[-1]
    assert "extract_status='error'" in update_sql
    assert update_params == ("file missing", 42)


def test_extract_attachment_done_path(tmp_path, monkeypatch):
    real_file = tmp_path / "real.pdf"
    real_file.write_bytes(b"not a real pdf but exists on disk")

    fake_cursor = _FakeCursor(fetchone_result={"stored_path": str(real_file), "mime_type": "application/pdf"})
    fake_ctx = _FakeCursorCtx(fake_cursor)
    monkeypatch.setattr("database.get_db_cursor", fake_ctx)
    monkeypatch.setattr(svc, "extract_text_from_file", lambda path, mime_type=None: ("body", False))

    status = svc.extract_attachment(1)

    assert status == "done"
    update_sql, update_params = fake_cursor.executed[-1]
    assert "extract_status='done'" in update_sql
    assert update_params == ("body", False, 1)


def test_extract_attachment_never_raises_on_db_error(monkeypatch):
    """A DB error on the very first fetch (before any row is even read) must be
    swallowed — extract_attachment() must return 'error', never propagate, so a
    single bad row can never abort run_attachment_extraction()'s batch loop."""

    def _boom(commit=True):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom)

    status = svc.extract_attachment(99)

    assert status == "error"
