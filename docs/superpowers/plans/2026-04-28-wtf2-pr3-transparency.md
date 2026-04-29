# WTF 2.0 — PR 3: Radical Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Radical Transparency — full public methodology page on what-the-fact.tech, live article scorer endpoint, "How we scored this" panel on consumer articles, and a user error-flagging form.

**Architecture:** /transparency is a Flask render_template page on wtf-tech; /api/v1/score proxies to hub wtf-hub/api/analyze with IP-based in-memory rate limiting; error flags write to wtf.score_flags; consumer article.html gets an expandable transparency panel.

**Tech Stack:** Flask + Jinja2 (wtf-tech), SQLAlchemy + text() (flag writes), requests (hub proxy), in-memory dict rate limiter.

---

Refer to the full Plan 3 content generated during design session. Key tasks:

1. DB Migration 007 — wtf.score_flags table
2. /transparency methodology page on wtf-tech
3. /score endpoint (rate-limited) + /flag endpoint
4. "How we scored this" panel on consumer article.html
5. Smoke tests
6. VPS rebuild

See brainstorm session output for complete code for all 6 tasks.

## Success Criteria

- /transparency page renders with live article counts + methodology docs
- /score accepts POST {text} and returns bias + factcheck + geo JSON
- 6th /score request returns 429 rate limit
- /flag writes to wtf.score_flags successfully
- "How we scored this" panel visible on consumer article page
- VPS deployed and all endpoints return 200
