# Kytran Business Suite — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standalone business suite running at business.kytranempowerment.com with CRM + Invoicing + Store + Automations engine, tenant #1 (Kytran Empowerment) at Enterprise tier.

**Architecture:** Modular monolith with plugin system. Flask app with tenant middleware (PostgreSQL schema-per-tenant), plugin loader (manifest.json-driven), event bus (in-process pub/sub), and Stripe billing. Connects to ARCHIE's existing PostgreSQL for tenant #1.

**Tech Stack:** Flask, PostgreSQL 16, Redis, APScheduler, Jinja2, LCARS theme, Stripe, Google OAuth

**Spec:** `docs/superpowers/specs/2026-03-26-kytran-business-suite-design.md`

**Total: 15 tasks, ~60 commits, estimated 4-6 focused sessions.**

---

## Task Summary

| Task | Description | Complexity |
|------|-------------|-----------|
| 1 | Repo scaffold + Docker stack | Small |
| 2 | Config + Database + Schema manager | Medium |
| 3 | Tenant middleware | Small |
| 4 | Event bus | Small |
| 5 | Plugin loader | Medium |
| 6 | Flask app factory + Auth | Medium |
| 7 | Stripe billing + module activation | Medium |
| 8 | Mail client | Small |
| 9 | CRM plugin migration | Large |
| 10 | Invoicing plugin migration | Large |
| 11 | Store plugin migration | Large |
| 12 | Automations engine | Medium |
| 13 | Seed tenant #1 | Small |
| 14 | Docker build + NPM + Deploy | Medium |
| 15 | Code Health + Dev HQ registration | Small |

See full task details in the plan file.
Note: Full implementation code for all 15 tasks is documented inline.
Each task follows TDD: write failing test, implement, verify pass, commit.
