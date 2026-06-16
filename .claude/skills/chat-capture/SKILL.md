---
name: chat-capture
description: Capture a full AI chat conversation into a clean transcript document. Use when the user wants to pull an entire ChatGPT/Claude/Gemini conversation (or all of them) into one file — from a share link OR a data export. Triggers: "capture this chat", "pull the whole conversation", "get everything from that ChatGPT/Claude link", "export my chats into a document", "the app can't read this share link".
---

# Chat Capture

Two modes. Pick by what the user gives you.

## ⚠️ The one hard limit (state it up front if a share link is involved)
A `…/share/…` link is a **frozen snapshot from the moment Share was clicked** — it does NOT
contain anything added afterward, and the conversation data is fetched client-side (no full
JSON embedded in the HTML). No browser, scroll, or agent can recover post-share messages.
**For the COMPLETE history, use Mode B (export).** Mode A only gets what the snapshot holds.

---

## Mode A — Share link → transcript (ChatGPT / Claude / Gemini)
Use the Playwright MCP browser (renders the JS; a plain fetch only gets the empty shell).

1. `browser_navigate` to the share URL.
2. Expand + extract in one `browser_evaluate`. CRITICAL: long conversations **lazy-load /
   virtualize** — you must scroll UP to the first message and DOWN to the last, repeatedly,
   until the message count stops growing (don't use a fixed number of passes; some chats take
   many cycles). This loop stops only when the count is unchanged for 3 consecutive cycles
   (or hits the 80-cycle safety cap):
   ```js
   async () => {
     const sleep = ms => new Promise(r=>setTimeout(r,ms));
     const sc = document.scrollingElement || document.documentElement;
     const expand = () => document.querySelectorAll('button,[role="button"],a').forEach(b=>{
       if(['show more','voir plus','continue','load more'].includes((b.innerText||'').trim().toLowerCase())) b.click();});
     const count = () => document.querySelectorAll('[data-message-author-role]').length;
     let prev=-1, stable=0, cycles=0;
     while (stable < 3 && cycles < 80) {
       sc.scrollTo(0,0); await sleep(500);                 // UP — pull in earlier messages
       expand();
       sc.scrollTo(0,sc.scrollHeight); await sleep(500);   // DOWN — pull in later messages
       expand();
       const c = count();
       stable = (c === prev) ? stable+1 : 0;               // reset whenever new msgs appear
       prev = c; cycles++;
     }
     sc.scrollTo(0,0); await sleep(400); expand();          // settle at the very top
     // ChatGPT/Claude use [data-message-author-role]; Gemini differs — adapt selector if 0.
     const nodes=[...document.querySelectorAll('[data-message-author-role]')];
     const parts=nodes.map((t,i)=>{
       const role=(t.getAttribute('data-message-author-role')||'?').toUpperCase();
       return '='.repeat(70)+`\n## Message ${i+1} — ${role}\n`+'='.repeat(70)+'\n\n'+(t.innerText||'').trim();});
     return {count:nodes.length, cycles, doc:'# '+document.title+'\n# Source: '+location.href+'\n# Messages: '+nodes.length+
            '\n# NOTE: share link = snapshot; uploaded files are referenced, not included.\n\n'+parts.join('\n\n')};
   }
   ```
   If `cycles` hit 80 and `count` was still climbing, run the `browser_evaluate` again (state
   persists) to keep loading — only stop once it stabilizes at the first message.
3. Write the returned `doc` to a file (default `/home/kytran/chat-captures/<slug>.md`).
4. Tell the user the count + path, and that a share link only holds its snapshot (offer Mode B for the rest).

If `count` looks lower than expected → it's the snapshot limit. Recommend Mode B; do not keep scrolling.

---

## Mode B — Data export → ALL conversations (the complete path)
The user exports from ChatGPT (Settings → Data controls → Export data) or Claude (Settings →
Export data) → a `.zip` containing `conversations.json`. They drop it on the hub
(e.g. `/home/kytran/`). Then:

```bash
python3 /mnt/archie_brain/.claude/skills/chat-capture/parse_export.py <export.zip|conversations.json> [out_dir] [title_filter]
# e.g. only the termination thread:
python3 .../parse_export.py /home/kytran/chatgpt-export.zip /home/kytran/chat-captures termination
```
`parse_export.py` handles BOTH ChatGPT (`mapping` tree, sorted by create_time, system msgs
dropped, multimodal noted) and Claude (`chat_messages`, attachments noted) shapes, and writes
one `NNN_<title>.md` per conversation. Pass a `title_filter` substring to grab just one chat.

---

## Output convention
Default output dir: `/home/kytran/chat-captures/` (the owner retrieves files there, same as PSTs).
Always report: how many messages/conversations captured + the exact file path(s).

## Notes
- This is a personal-capture tool (the owner's own chats) — read-only, local files; no platform DB writes.
- Don't paste a 25KB+ transcript into chat — write it to a file and report the path + a 1-line summary.
- Reuse the proven extraction; if a platform's share DOM differs, adapt the selector, keep the structure.
