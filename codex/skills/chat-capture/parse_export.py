#!/usr/bin/env python3
"""parse_export.py — turn a ChatGPT or Claude data export into clean per-conversation
Markdown transcripts (the COMPLETE history, unlike a share link which is only a snapshot).

Usage:
    python3 parse_export.py <conversations.json | export.zip> [out_dir]
    python3 parse_export.py ~/chatgpt-export.zip ~/chat-captures
    python3 parse_export.py "Terry"   # + a path → filter conversations whose title matches

Handles:
  * ChatGPT export: a JSON list of conversations, each with a `mapping` (node tree).
  * Claude export:  a JSON list of conversations, each with `chat_messages` (ordered).
Defensive: unknown shapes are skipped with a warning, never crash the whole run.
"""
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone


def _slug(s, n=80):
    s = re.sub(r"\s+", "_", (s or "untitled").strip())
    s = re.sub(r"[^A-Za-z0-9._-]", "", s)
    return (s or "untitled")[:n]


def _ts(v):
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _parts_text(content):
    """ChatGPT message content -> text. parts may be strings or multimodal dicts."""
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts") or []
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            # multimodal (image/file/audio) — note it, don't crash
            t = p.get("text") or p.get("content_type") or p.get("asset_pointer") or ""
            out.append(f"[{p.get('content_type', 'attachment')}]" if not p.get("text") else t)
    return "\n".join(x for x in out if x).strip()


def _chatgpt_linear(conv):
    """Linearize a ChatGPT `mapping` tree into ordered (role, text, ts) tuples."""
    mapping = conv.get("mapping") or {}
    msgs = []
    for node in mapping.values():
        m = (node or {}).get("message")
        if not m:
            continue
        role = ((m.get("author") or {}).get("role")) or "unknown"
        if role == "system":
            continue
        text = _parts_text(m.get("content"))
        if not text:
            continue
        msgs.append((m.get("create_time") or 0, role, text))
    msgs.sort(key=lambda x: x[0] or 0)
    return [(r, t, _ts(ct)) for ct, r, t in msgs]


def _claude_linear(conv):
    """Claude `chat_messages` -> ordered (role, text, ts)."""
    out = []
    for m in conv.get("chat_messages") or []:
        role = "user" if (m.get("sender") == "human") else (m.get("sender") or "assistant")
        text = m.get("text") or ""
        if not text and m.get("content"):  # newer claude exports use content[].text
            text = "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict))
        for a in m.get("attachments") or []:
            text += f"\n[attachment: {a.get('file_name', 'file')}]"
        if text.strip():
            out.append((role, text.strip(), m.get("created_at", "")))
    return out


def _write(conv_title, created, msgs, out_dir, idx):
    if not msgs:
        return None
    fn = f"{idx:03d}_{_slug(conv_title)}.md"
    path = os.path.join(out_dir, fn)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# {conv_title or 'Untitled conversation'}\n")
        if created:
            fh.write(f"_{created}_ · {len(msgs)} messages\n")
        fh.write("\n")
        for role, text, ts in msgs:
            fh.write("=" * 70 + f"\n## {role.upper()}" + (f"  ·  {ts}" if ts else "") + "\n" + "=" * 70 + "\n\n")
            fh.write(text + "\n\n")
    return path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(src)) or ".", "chat-captures")
    title_filter = sys.argv[3].lower() if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)

    # Load conversations.json (directly, or from a zip) — fail with a clear message, not a trace.
    if not os.path.exists(src):
        print(f"ERROR: file not found: {src}"); sys.exit(2)
    try:
        if src.endswith(".zip"):
            with zipfile.ZipFile(src) as z:
                name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                if not name:
                    print("ERROR: no conversations.json inside the zip"); sys.exit(2)
                data = json.loads(z.read(name))
        else:
            with open(src, encoding="utf-8") as fh:
                data = json.load(fh)
    except (json.JSONDecodeError, zipfile.BadZipFile, OSError, UnicodeDecodeError) as e:
        print(f"ERROR: could not read export ({type(e).__name__}): {e}"); sys.exit(2)

    convs = data if isinstance(data, list) else [data]
    written = 0
    for i, conv in enumerate(convs, 1):
        if not isinstance(conv, dict):
            continue
        title = conv.get("title") or conv.get("name") or f"conversation_{i}"
        if title_filter and title_filter not in title.lower():
            continue
        created = _ts(conv.get("create_time")) or conv.get("created_at", "")
        if "mapping" in conv:
            msgs = _chatgpt_linear(conv)
        elif "chat_messages" in conv:
            msgs = _claude_linear(conv)
        else:
            print(f"  skip (unknown shape): {title}"); continue
        p = _write(title, created, msgs, out_dir, i)
        if p:
            written += 1
            print(f"  wrote {os.path.basename(p)}  ({len(msgs)} msgs)")
    print(f"\nDone: {written} conversation(s) -> {out_dir}")


if __name__ == "__main__":
    main()
