"""Skill: chat_capture — render a public AI chat SHARE link (ChatGPT / Claude) and
extract the visible transcript as ordered (role, text) messages.

Used by S.C.O.U.T. to autonomously capture a shared conversation server-side and hand it to
the Mailbox Story Extractor (platform side: services/mailbox_scout_capture.py ->
mailbox_chat_service.ingest_chat). A share link is a frozen SNAPSHOT — it only contains what
was visible when shared; the data-export path remains the source of truth for the COMPLETE
history. This skill is the convenience / autonomous path for a single shared thread.

params: (none required)
returns: {"data": {"title", "source_url", "messages": [[role, text], ...], "selector"},
          "auto_approve": True, "findings": "<n> messages (<selector>)"}
"""
import logging

logger = logging.getLogger(__name__)

# JS run in the page to pull ordered (role, text) pairs. Tries, in order:
#   1. ChatGPT share: [data-message-author-role]
#   2. Claude share:  .font-user-message / .font-claude-message (in document order)
#   3. generic fallback: <main> (or body) innerText as one 'unknown' message — never empty
_EXTRACT_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/ /g, ' ').trim();
  // 1. ChatGPT
  let nodes = Array.from(document.querySelectorAll('[data-message-author-role]'));
  if (nodes.length) {
    const out = [];
    for (const n of nodes) {
      const role = n.getAttribute('data-message-author-role') || 'unknown';
      const t = clean(n.innerText);
      if (t) out.push([role, t]);
    }
    if (out.length) return {title: document.title, messages: out, selector: 'chatgpt'};
  }
  // 2. Claude — user/assistant message blocks, in DOM order
  nodes = Array.from(document.querySelectorAll(
    '.font-user-message, .font-claude-message, [data-testid="user-message"]'));
  if (nodes.length) {
    const out = [];
    for (const n of nodes) {
      const role = (n.className || '').includes('claude') ? 'assistant' : 'user';
      const t = clean(n.innerText);
      if (t) out.push([role, t]);
    }
    if (out.length) return {title: document.title, messages: out, selector: 'claude'};
  }
  // 3. fallback — whole main text as one message (never return nothing)
  const main = document.querySelector('main') || document.body;
  const t = clean(main && main.innerText);
  return {title: document.title, messages: t ? [['unknown', t]] : [], selector: 'fallback'};
}
"""


def run(page, url, params, job_id):
    if not url:
        return {"data": {"messages": []}, "findings": "no url", "auto_approve": True}
    page.goto(url, wait_until="networkidle", timeout=45000)
    # scroll-until-stable: long shares lazy-render as you scroll. Stop when the ChatGPT
    # message count holds steady for 3 ticks, or after a hard cap (~42s).
    prev, stable = -1, 0
    for _ in range(60):
        count = page.evaluate(
            "() => document.querySelectorAll('[data-message-author-role]').length"
        )
        if count == prev:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        prev = count
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)
    page.evaluate("() => window.scrollTo(0, 0)")

    extracted = page.evaluate(_EXTRACT_JS) or {}
    messages = extracted.get("messages") or []
    data = {
        "title": extracted.get("title") or "shared conversation",
        "source_url": url,
        "messages": messages,
        "selector": extracted.get("selector"),
    }
    logger.info(
        "chat_capture job #%s: %d messages (%s)", job_id, len(messages), data["selector"]
    )
    return {
        "data": data,
        "screenshots": [],
        "auto_approve": True,
        "findings": f"{len(messages)} messages ({data['selector']})",
    }
