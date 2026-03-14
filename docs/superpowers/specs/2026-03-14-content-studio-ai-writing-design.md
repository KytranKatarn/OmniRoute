# Content Studio: AI Writing Powerhouse — Design Spec

## Overview

Upgrade Content Studio with 5 multi-agent writing pipeline (Research→Outline→Draft→Edit→SEO), content templates, rich writing UI with AI assist buttons, and real export. Agents registered at CREATIVE station.

## 5 Writing Agents

- Scout (research) — gathers key points, sources, context
- Mapper (outline) — structures content with sections/headers
- Quill (writer) — drafts full content from outline
- Razor (editor) — polishes grammar/tone/clarity, can request revisions (max 2 rounds)
- Beacon (seo) — optimizes search, meta, keywords, readability score

## Pipeline

research → outline → draft → edit → (revision loop if quality < 70, max 2 rounds) → SEO → done. Checkpoints at outline + final edit. Stored in content_writing_sessions table.

## Content Templates (8)

article, blog_post, press_release, product_review, how_to_guide, newsletter, marketing_copy, book_chapter. Each has structure hints fed to the outline agent.

## Database

New table: content_writing_sessions (id, document_id FK, user_id, description, current_stage, status, stage_outputs JSONB, created_at, completed_at). 5 agents INSERT into agents table.

## Routes (4 new)

POST /api/ai/write — start writing pipeline (description, content_type, tone, template)
GET /api/ai/write/<session_id> — pipeline status
POST /api/ai/write/<session_id>/approve — approve checkpoint
POST /api/ai/assist — inline AI actions (expand, rewrite, summarize, change_tone) on selected text

## Frontend

Upgrade template: writing view with word count, tone selector, AI assist toolbar (Expand, Rewrite, Summarize, Tone buttons), "Write with AI" pipeline launcher. Fix AI fallback to show proper error.

## Export fix

Real Markdown + HTML download via /api/documents/<id>/export?format=md|html

## Files: ~500 lines new, ~100 modified
