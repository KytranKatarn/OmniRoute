# Opencode guard-free terminal — spec

**Status:** BUILT and RUNNING. Image `archie_opencode_terminal_guardfree:latest`
(built 2026-09-27), container `archie_opencode_terminal_gf` on
`127.0.0.1:17687`.
**Date:** 2026-09-27 · **remediated:** 2026-09-28
**Scope of authorship:** `docs/` (in-lane). The Dockerfile itself is `opencode/`,
which is outside `config/agents/opencode.yaml` `allowed_paths` — the owner applies it.

**This file is the index.** It was one 26,605-char document; it is split into four
parts because F.O.R.G.E. reviews per file, and one file that size cannot be read in
a single pass — it was truncated at ~62% and a partial read of the quoted
before/after text produced a false CRITICAL. Every part is now under the 9,000-char
pass window. Nothing was dropped: the parts below are the original text verbatim.

## Goal

Run an opencode terminal with no scope guard, so it can read, edit, commit, and
push anywhere in the repo on an `opencode/*` branch — the same posture Claude-CLI
has. Safety moves entirely to the layers that already exist and are not lane-local:
pre-commit, F.O.R.G.E. review, and GitHub branch protection.

## Decisions on record

Both owner decisions, so a reader who lands here does not have to open a part to
learn what was decided:

- **2026-09-27 — the guard-free lane itself is wanted.** The ask was
  Claude-CLI-equivalent access; that is what this is. Recorded in
  [part 1](2026-09-27-opencode-guard-free-terminal-1-build-and-verification.md).
- **2026-09-28 — the `/run/secrets/opencode_github_token` mount is DELIBERATE.**
  Measured in all three instances; the residue is `opencode-pr`'s stale "NOT MOUNTED
  YET" header, which is an owner task (`opencode/` is out of lane scope). Full
  reasoning in
  [part 2](2026-09-27-opencode-guard-free-terminal-2-decisions-and-inspection.md).

## The four parts

| Part | Covers |
|---|---|
| [1 — Build, verification, and rollback](2026-09-27-opencode-guard-free-terminal-1-build-and-verification.md) | Enforcement surfaces as verified, the Dockerfile, the `--verify` assertions, what remains, rollback |
| [2 — Decisions and first inspection](2026-09-27-opencode-guard-free-terminal-2-decisions-and-inspection.md) | The token-mount decision; the three gaps found on first inspection and how each closed |
| [3 — Lane instructions](2026-09-27-opencode-guard-free-terminal-3-lane-instructions.md) | The same defect on a second surface (lane instructions), the tracked doc set, what is actually known about `main` protection |
| [4 — The guarded lane](2026-09-27-opencode-guard-free-terminal-4-guarded-lane.md) | Why the guarded lane needed the same treatment and is a genuinely different instruction set |
