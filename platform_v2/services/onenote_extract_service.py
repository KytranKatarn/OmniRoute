"""onenote_extract_service.py — Mailbox Story Extractor: OneNote (.one) ingestion engine.

Companion to mailbox_extract_service.py (which handles Outlook .pst). OneNote section files
(.one) and table-of-contents (.onetoc2) are a binary format (MS-ONESTORE) with poor FOSS tooling
on Linux. We do NOT shell out to a parser — we decode the file's text directly:

    bytes.decode("utf-16-le", errors="ignore")  ->  one big string of every UTF-16LE text run
    interleaved with binary garbage  ->  extract printable runs  ->  filter formatting/GUID noise.

This recovers the readable prose + pasted emails + contact lists (validated on real GC SPAC-TIC
notebooks: 'SPC et SPAC - PROCESSUS' -> ~5,300 clean lines). It is text-only:

  * Pages that are embedded PRINTOUTS / IMAGES (e.g. screenshots of emails) yield NO text and
    need OCR (Phase 2) — extract_onenote reports them as image_only so the caller can flag them.
  * Rich formatting/page boundaries are approximated by size-based chunking, not the real tree.

PRIVACY: everything is local. No network, no cloud OneNote API (mandatory for GC documents).
Each extracted chunk becomes a `mailbox_emails` row (folder=notebook, body_text=chunk) so the
existing local-only enrichment + story + reader pipeline processes it unchanged.

Usage (from the upload route's background job, or the /api/import-onenote route):
    n = extract_onenote(import_id, '/mnt/data2/mailbox_story/<id>/source.one',
                        '/mnt/data2/mailbox_story/<id>/eml')
src_path may be a single .one/.onetoc2 file, a DIRECTORY of them, or a .zip of a notebook folder.
"""

import logging
import os
import re
import stat
import zipfile

from database import get_db_cursor

logger = logging.getLogger(__name__)

# OneNote section file header GUID {7B5C52E4-D88C-4DA7-AEB1-5378D02996D3} as on-disk bytes.
ONENOTE_MAGIC = bytes([0xE4, 0x52, 0x5C, 0x7B, 0x8C, 0xD8, 0xA7, 0x4D, 0xAE, 0xB1, 0x53, 0x78, 0xD0, 0x29, 0x96, 0xD3])
PST_MAGIC = b"!BDN"

_CHUNK_CHARS = 6000  # ~a page of text per mailbox_emails row (keeps enrichment dispatches small)
_BODY_CAP = 16000  # hard cap per row body
_MAX_CHUNKS = 400  # per notebook, runaway guard
_MIN_NOTEBOOK_CHARS = 40  # below this a .one is treated as image-only / empty

# Readable UTF-16LE run: printable ASCII + Latin-1/Extended-A (covers é à ç etc.), len >= 6.
_RUN_RE = re.compile(r"[\x20-\x7e -ɏ]{6,}")
# Formatting / structural noise emitted by the binary store that isn't human content.
_NOISE_RE = re.compile(
    r"xmlns|schemas\.|onenote:|resolutionId|localId|O365id|sharepoint\.com|PageTitle|"
    r"PageDateTime|MediaReference|^(Calibri|Arial|Times New Roman|Calibri Light|Cambria|"
    r"Verdana|Tahoma|Segoe|Consolas|Wingdings|Symbol)\b",
    re.I,
)


def file_kind(path):
    """Sniff the first bytes: 'pst' | 'onenote' | 'unknown'. Content-based, not extension-based."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except Exception:
        return "unknown"
    if head[:4] == PST_MAGIC:
        return "pst"
    if head[:16] == ONENOTE_MAGIC:
        return "onenote"
    return "unknown"


def _mark_error(import_id, message):
    """Flip an import to 'error' with a bounded message. Never raises (best-effort)."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE mailbox_imports SET status='error', error=%s WHERE id=%s",
                ((message or "onenote extraction failed")[:1000], import_id),
            )
    except Exception:
        logger.exception("could not mark import %s as error", import_id)


def clean_runs(text):
    """Decode-noise -> ordered list of human-readable text runs (dedup consecutive repeats)."""
    out = []
    for s in _RUN_RE.findall(text):
        s = s.strip()
        if len(s) < 6:
            continue
        # keep prose, email-ish header lines, or anything with an address; drop pure noise
        is_prose = re.search(r"[A-Za-zÀ-ÿ]{3,}\s+\S+\s+[A-Za-zÀ-ÿ]", s)
        is_hdr = re.match(r"(?i)(from|de|sent|envoy|to|à|cc|subject|objet)\s*:", s)
        if not (is_prose or is_hdr or "@" in s):
            continue
        if _NOISE_RE.search(s):
            continue
        if re.fullmatch(r"[0-9A-Fa-f\-]{12,}", s):  # bare GUID / hex blob
            continue
        if re.fullmatch(r"[0-9A-Fa-f]{16,}@\S+", s):  # OneNote object-id pseudo-address, not real mail
            continue
        out.append(s)
    deduped = []
    for x in out:
        if not deduped or deduped[-1] != x:
            deduped.append(x)
    return deduped


def extract_one_text(path):
    """One .one/.onetoc2 file -> list of clean text runs (UTF-16LE decode heuristic).

    Text runs in the binary store can sit at either byte parity, so we decode at BOTH
    alignments (offset 0 and 1), keep the richer one as primary, and append any unique runs
    from the other — no text is missed for being at an odd offset.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except Exception as exc:
        logger.warning("onenote: could not read %s: %s", path, exc)
        return []
    runs_a = clean_runs(data.decode("utf-16-le", errors="ignore"))
    runs_b = clean_runs(data[1:].decode("utf-16-le", errors="ignore"))
    primary, other = (runs_a, runs_b) if sum(map(len, runs_a)) >= sum(map(len, runs_b)) else (runs_b, runs_a)
    seen = set(primary)
    runs = primary + [r for r in other if r not in seen]
    logger.debug("onenote: %s -> %d text runs (%d chars)", path, len(runs), sum(map(len, runs)))
    return runs


def _chunk(runs):
    """Join runs into ~page-sized text chunks (break at run boundaries, never mid-line)."""
    chunks, buf, size = [], [], 0
    for r in runs:
        if size + len(r) > _CHUNK_CHARS and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(r)
        size += len(r) + 1
        if len(chunks) >= _MAX_CHUNKS:
            break
    if buf and len(chunks) < _MAX_CHUNKS:
        chunks.append("\n".join(buf))
    return chunks


def _safe_extractall(zip_path, dest):
    """Extract a zip, rejecting Zip Slip (../ or absolute member paths) and symlink members.

    Extracts member-by-member so unsafe entries are SKIPPED, not just detected. Defense in depth
    even though the route is admin-gated — a crafted .one-export zip could otherwise write outside
    `dest` or plant a symlink.
    """
    dest_real = os.path.realpath(dest)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename
            if stat.S_ISLNK(member.external_attr >> 16):  # zip symlink entry
                logger.warning("onenote: skipping symlink zip entry %s", name)
                continue
            target = os.path.realpath(os.path.join(dest, name))
            if target != dest_real and not target.startswith(dest_real + os.sep):
                logger.warning("onenote: skipping unsafe (path-traversal) zip entry %s", name)
                continue
            zf.extract(member, dest)


def _iter_one_files(src_path):
    """Yield (notebook_name, file_path) for every .one/.onetoc2 under src_path.

    src_path may be a single file, a directory tree, or a .zip (extracted alongside).
    """
    exts = (".one", ".onetoc2")
    if os.path.isfile(src_path):
        if src_path.lower().endswith(".zip"):
            dest = src_path + ".extracted"
            try:
                _safe_extractall(src_path, dest)
            except Exception as exc:
                logger.warning("onenote: bad zip %s: %s", src_path, exc)
                return
            yield from _iter_one_files(dest)
            return
        if src_path.lower().endswith(exts):
            yield os.path.splitext(os.path.basename(src_path))[0], src_path
        return
    for root, _dirs, files in os.walk(src_path):
        for fn in sorted(files):
            if fn.lower().endswith(exts):
                yield os.path.splitext(fn)[0], os.path.join(root, fn)


def extract_onenote(import_id, src_path, out_dir):
    """Extract every OneNote notebook under `src_path` into mailbox_emails rows.

    Returns the number of rows ingested. Marks the import 'error' on hard failure.
    Notebooks that yield no text (image/printout-only) are skipped but counted in the log so
    the caller knows OCR (Phase 2) is needed for them.
    """
    os.makedirs(out_dir, exist_ok=True)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET status='extracting' WHERE id=%s", (import_id,))

    files = list(_iter_one_files(src_path))
    if not files:
        _mark_error(import_id, f"no .one/.onetoc2 files found at {src_path}")
        return 0

    count = 0
    image_only = []
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            for notebook, fpath in files:
                runs = extract_one_text(fpath)
                text_len = sum(len(r) for r in runs)
                if text_len < _MIN_NOTEBOOK_CHARS:
                    image_only.append(notebook)
                    continue
                chunks = _chunk(runs)
                for i, chunk in enumerate(chunks, 1):
                    subject = notebook if len(chunks) == 1 else f"{notebook} · p{i}"
                    cur.execute(
                        """INSERT INTO mailbox_emails
                               (import_id, folder, subject, body_text, has_attachments, enrich_status)
                           VALUES (%s, %s, %s, %s, false, 'pending')""",
                        (import_id, notebook[:255], subject[:255], chunk[:_BODY_CAP]),
                    )
                    count += 1
            note = ""
            if image_only:
                note = f"image-only (need OCR): {', '.join(image_only[:20])}"
            cur.execute(
                "UPDATE mailbox_imports SET status='extracted', email_count=%s, error=%s WHERE id=%s",
                (count, note or None, import_id),
            )
    except Exception as exc:
        logger.exception("onenote import %s failed during ingest", import_id)
        _mark_error(import_id, f"onenote ingest failed after {count} rows: {exc}")
        return 0

    logger.info(
        "onenote import %s: %d page-rows from %d notebook(s); %d image-only (%s)",
        import_id,
        count,
        len(files),
        len(image_only),
        ", ".join(image_only) or "none",
    )
    return count
