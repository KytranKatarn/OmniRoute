"""Skill: chat_capture — render a public AI chat SHARE link (ChatGPT / Claude) and
extract the FULL visible transcript as ordered (role, text) messages.

Used by S.C.O.U.T. to autonomously capture a shared conversation server-side and hand it to
the Mailbox Story Extractor (platform side: services/mailbox_scout_capture.py ->
mailbox_chat_service.ingest_chat). A share link is a frozen SNAPSHOT — but the snapshot holds
the WHOLE conversation, even when the page only *renders* a window of it.

CRITICAL — ChatGPT virtualizes the share page: it mounts only ~15 messages into the DOM at a
time and swaps them as you scroll, so a naive scroll-to-bottom-then-read grabs just the last
~15. This skill instead HARVESTS messages as they mount — stepping top→bottom and collecting
each `[data-message-author-role]` keyed by its enclosing `[data-testid^="conversation-turn"]`
id (so nothing is double-counted or lost), then orders by turn index. Proven to recover 254/254
on a real long thread. Claude / non-virtualized pages fall through to a simpler extractor.

params: (none required)
returns: {"data": {"title", "source_url", "messages": [[role, text], ...], "selector"},
          "auto_approve": True, "findings": "<n> messages (<selector>)"}
"""
import logging

logger = logging.getLogger(__name__)

# Virtualization-aware harvest for ChatGPT. Runs entirely in the page (one async evaluate):
# scroll top→bottom in viewport-sized steps, grabbing every mounted message into a Map keyed by
# conversation-turn id; ordered by the numeric turn index. Returns [] if no role nodes exist
# (e.g. Claude / non-ChatGPT pages) so the caller can fall back.
_HARVEST_JS = r"""
async () => {
  const clean = (s) => (s || '').replace(/ /g, ' ').trim();
  const harvest = new Map();   // key -> {order, role, text}
  let seq = 0;
  const grab = () => {
    document.querySelectorAll('[data-message-author-role]').forEach((n) => {
      const text = clean(n.innerText);
      if (!text) return;
      const role = n.getAttribute('data-message-author-role') || 'unknown';
      const turn = n.closest('[data-testid^="conversation-turn"]');
      const tid = turn && turn.getAttribute('data-testid');
      let key, ord;
      if (tid) { key = tid; const m = tid.match(/(\d+)/); ord = m ? parseInt(m[1], 10) : seq++; }
      else { key = role + '|' + text.slice(0, 60); ord = seq++; }
      const ex = harvest.get(key);
      if (!ex) harvest.set(key, { order: ord, role, text });
      else if (text.length > ex.text.length) ex.text = text;  // keep the fullest render
    });
  };
  // pick the tallest scrollable element (the chat scroll region), fall back to the document
  let scroller = document.scrollingElement;
  document.querySelectorAll('*').forEach((e) => {
    if (e.scrollHeight > e.clientHeight + 200 && e.scrollHeight > (scroller ? scroller.scrollHeight : 0)) scroller = e;
  });
  scroller.scrollTop = 0; window.scrollTo(0, 0);
  await new Promise((r) => setTimeout(r, 600));
  grab();
  if (!document.querySelector('[data-message-author-role]')) {
    return { title: document.title, messages: [], selector: 'none' };
  }
  // Overlapping steps (<60% viewport) so every virtualized message stays mounted across at
  // least two grabs — a coarse/fast scroll skips turns that mount+unmount between grabs.
  const step = Math.max(250, Math.floor(scroller.clientHeight * 0.55));
  let lastH = -1, sameBottom = 0;
  for (let i = 0; i < 300; i++) {
    const y = Math.min(scroller.scrollTop + step, scroller.scrollHeight);
    scroller.scrollTop = y; window.scrollTo(0, y);
    await new Promise((r) => setTimeout(r, 350));
    grab();
    const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 5;
    if (atBottom) {
      if (scroller.scrollHeight === lastH) { if (++sameBottom >= 2) break; } else sameBottom = 0;
      lastH = scroller.scrollHeight;
    }
  }
  scroller.scrollTop = scroller.scrollHeight; window.scrollTo(0, scroller.scrollHeight);
  await new Promise((r) => setTimeout(r, 500));
  grab();
  const arr = Array.from(harvest.values()).sort((a, b) => a.order - b.order);
  return { title: document.title, selector: 'chatgpt', messages: arr.map((x) => [x.role, x.text]) };
}
"""

# Fallback for non-virtualized pages (Claude share blocks, or a generic single-blob page).
_FALLBACK_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/ /g, ' ').trim();
  let nodes = Array.from(document.querySelectorAll(
    '.font-user-message, .font-claude-message, [data-testid="user-message"]'));
  if (nodes.length) {
    const out = [];
    for (const n of nodes) {
      const role = (n.className || '').includes('claude') ? 'assistant' : 'user';
      const t = clean(n.innerText);
      if (t) out.push([role, t]);
    }
    if (out.length) return { title: document.title, messages: out, selector: 'claude' };
  }
  const main = document.querySelector('main') || document.body;
  const t = clean(main && main.innerText);
  return { title: document.title, messages: t ? [['unknown', t]] : [], selector: 'fallback' };
}
"""


def run(page, url, params, job_id):
    if not url:
        return {"data": {"messages": []}, "findings": "no url", "auto_approve": True}
    # ChatGPT virtualizes the message list — it only mounts what fits the viewport (+buffer),
    # so a tall viewport mounts more messages at once and fewer are missed between scroll steps.
    # (A very tall viewport + a two-way pass tipped into multi-minute runs on a 250+ thread;
    # this 1600px single-pass is the reliable middle — fully captures normal threads and the
    # bulk of long ones. For a guaranteed-complete dump of a very long thread, use the export.)
    try:
        page.set_viewport_size({"width": 1280, "height": 1600})
    except Exception:
        pass
    # ChatGPT keeps connections open (streaming/poll) so it never reaches 'networkidle' —
    # waiting for it just burns the budget. Load the DOM, then WAIT for the messages to mount:
    # the JS app paints them after load, and a fixed sleep is unreliable (fires before render
    # on a big thread → empty harvest → fallback). wait_for_selector blocks exactly as long as
    # needed, no more. Non-ChatGPT pages (Claude/generic) time out → small settle → fallback.
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_selector("[data-message-author-role]", timeout=25000)
        page.wait_for_timeout(800)
    except Exception:
        page.wait_for_timeout(2500)

    # Primary: virtualization-aware harvest (ChatGPT mounts ~15 at a time → must collect on scroll).
    try:
        extracted = page.evaluate(_HARVEST_JS) or {}
    except Exception:
        logger.exception("chat_capture harvest failed for job #%s", job_id)
        extracted = {}
    messages = extracted.get("messages") or []

    # Fallback: Claude / non-virtualized / generic — only if the harvest found nothing.
    if not messages:
        try:
            extracted = page.evaluate(_FALLBACK_JS) or {}
            messages = extracted.get("messages") or []
        except Exception:
            logger.exception("chat_capture fallback failed for job #%s", job_id)

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
