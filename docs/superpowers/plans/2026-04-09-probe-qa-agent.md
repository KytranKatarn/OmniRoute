# P.R.O.B.E. QA Testing Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated QA testing agent that runs YAML-defined test suites (API + Playwright E2E), displays results in Repair Bay, generates PDF reports, and alerts via Telegram on failures.

**Architecture:** Service layer (qa_service.py, qa_spec_runner.py, qa_report_service.py) executes YAML specs using requests for API tests and headless Playwright for E2E flows. Results stored in 3 dedicated tables. Repair Bay gets a QA tab for on-demand runs and viewing results. Agent loop job runs suites every 6 hours.

**Tech Stack:** Python, Flask, requests, playwright, weasyprint (PDF), PyYAML, PostgreSQL (JSONB)

**Spec:** docs/superpowers/specs/2026-04-09-probe-qa-agent-design.md

---

## File Structure

| File | Responsibility |
|------|----------------|
| database/migrations/051_qa_tables.sql | Create qa_test_suites, qa_test_runs, qa_test_results tables |
| platform_v2/services/qa_service.py | Orchestrator: run suites, collect results, trigger alerts |
| platform_v2/services/qa_spec_runner.py | YAML parser + test executor (requests + Playwright) |
| platform_v2/services/qa_report_service.py | PDF report generation via weasyprint |
| platform_v2/tools/repair_bay/qa_routes.py | API endpoints for QA tab |
| platform_v2/tools/repair_bay/__init__.py | Modified: register QA routes |
| platform_v2/templates/tools/repair_bay.html | Modified: add QA tab button + panel |
| ai_bridge/agent_loop.py | Modified: add scheduled QA job |
| specs/qa/archie-critical-paths.yaml | Initial test suite for ARCHIE platform |

---

## Tasks

See spec doc for full code. Tasks are:

1. Database migration (3 tables + indexes)
2. QA Spec Runner - API tests (requests-based)
3. QA Spec Runner - Playwright E2E tests
4. QA Service - Orchestrator (run suite, store results, Telegram alerts)
5. QA Report Service - PDF generation (weasyprint)
6. QA Routes - Repair Bay API endpoints
7. Repair Bay QA Tab - UI (tab button + panel + JS)
8. Initial Test Suite - ARCHIE Critical Paths YAML
9. Agent Loop Job - Scheduled QA runs (every 6h)
10. Create P.R.O.B.E. Agent in Database
11. Website Agent Counts - Replace exact numbers with 15+/125+

## Execution Order

Tasks 1-6 are sequential (each builds on the previous).
Tasks 7-8 depend on Tasks 1-6.
Task 9 depends on Task 4.
Task 10 is independent (DB only).
Task 11 is independent (website only).
Tasks 10 and 11 can run in parallel with Tasks 7-9.
