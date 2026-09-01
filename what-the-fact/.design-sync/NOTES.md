# design-sync notes — what-the-fact.com

- Shape styles-only: bundle = consumer/static/style.css ONLY. tech/static/style.css (94 lines, what-the-fact.tech) deliberately excluded — different domain, ask owner before adding.
- Page-level styles live in per-template <style> blocks (wtf-bs-/wtf-dv-/wtf-ec-/wtf-mu-/wtf-wx- namespaces) — NOT extractable into the bundle; conventions header tells the agent new pages get their own namespace.
- No bare .wtf-card exists — the card is .wtf-article-card (+ per-lean modifiers). Don't invent base classes (same trap as LCARS components.css).
- design-reference/ holds Claude Design canvas artboards (.dc.html) from an earlier design session — unrelated to this sync, do not upload.
