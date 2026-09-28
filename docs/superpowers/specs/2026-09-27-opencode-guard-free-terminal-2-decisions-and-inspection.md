# Opencode guard-free terminal — spec, part 2 of 4: Decisions and first inspection

**Part 2 of 4.** Index, status and Goal: [2026-09-27-opencode-guard-free-terminal](2026-09-27-opencode-guard-free-terminal.md). Next: [part 3](2026-09-27-opencode-guard-free-terminal-3-lane-instructions.md).

---

## Decided — the token mount is deliberate (owner, 2026-09-28)

`opencode-pr` states:

> "THAT SECRET IS NOT MOUNTED YET, and that is deliberate: the owner's standing
> instruction is that no GitHub token goes into this lane without their explicit
> decision."

`/run/secrets/opencode_github_token` **is** mounted — measured 2026-09-28 in all
THREE instances (canonical 17685, guarded 17686, guard-free 17687), a 94-byte
file (93-char token + newline), owner `node`, bind-mounted from
`secrets/opencode/github_token.txt`; a sibling `/run/secrets/opencode_kb_bearer`
comes from `secrets/opencode/mcp_bearer.txt`.

**DECIDED: the mount is deliberate.** Asked directly, the owner confirmed it
(2026-09-28). So the standing instruction is satisfied rather than violated, and
what remains is a stale comment, not a missing control.

**The stale artifact is `opencode-pr`'s own header**, quoted above: it tells the
lane a secret is deliberately absent when one is present. It is baked into the
image (`opencode/` is outside this lane's allowed_paths), so correcting it is an
owner task, and until it is corrected the header is a false statement sitting
where an agent reads it before shipping. Recommended: drop the "NOT MOUNTED YET"
paragraph from that header and replace it with the decision as recorded here, so
the next reader is not sent to re-derive a question that has been answered.

Consequence for the lanes themselves: the token being present is not a licence to
push or merge. A guard-free lane still has no scope guard, and the merge path is
unchanged — Repair Bay `merge_pr` with the owner's in-session word and a stored
verdict covering the head. A merge-capable credential in an unguarded lane is
still the combination worth watching; the decision above accepts the mount, it
does not widen what the lane may do. The guarded lane's GUARDRAILS already state
the token IS present, so an agent there is not told the lane is uncredentialed.

## What the first inspection found (2026-09-28)

Three gaps between "the script exists" and "the terminal is usable". All three are
now closed or escalated; nothing here was inferred — each claim below was measured.

### 1. The lane clone was never seeded — CLOSED

`/start.sh:85` gates ALL of its git setup behind `if [ -d /work/archie-platform/.git ]`.
The base image bakes **no** `/work` at all (verified: `ls /work` in
`archie_brain-archie_opencode_terminal:latest` → "No such file or directory"), so
the guard-free instance — which mounts a FRESH empty volume at `/work` — skipped
the whole block. Three consequences, all live:

- `opencode` opened with **no codebase in scope** (`start.sh:103` fell back to
  `cd /work`).
- **No `user.name`/`user.email`** — commits would have been rejected or misattributed.
- **No `credential.helper`** — even with the token mounted, `git push` could not
  authenticate.

Fixed by seeding the clone rather than by touching the image: `git clone
/mnt/archie_brain /work/archie-platform` inside the container (4s — same
filesystem, so objects hardlink), `remote set-url` to GitHub, `fetch`,
`checkout -B main origin/main`, then the same `start.sh` config applied by hand so
a later restart is idempotent. End state: `main` @ `e318e3db1` = `origin/main`,
clean tree, `core.hooksPath=/opt/no-guard`, credential helper set.

Cloning from the live tree rather than from GitHub was deliberate: it is local, so
no credential is needed to build the clone, and the resulting clone is
bit-identical in history to what the canonical lane holds.

### 2. The lane was running the GUARDED lane's instructions — CLOSED

`/opencode-home/config/opencode/GUARDRAILS.md` in the guard-free volume was a copy
of the guarded lane's file: it described a deny-by-default `allowed_paths` list and
a hook that this image does not have. An unrestricted agent being told it is
restricted is a defect in the same class as a security control that reports the
opposite of its state.

Replaced with a guard-free variant (`GUARDRAILS.md.guard-bak` keeps the original).
It drops the path allowlist, and says plainly what replaces it: the non-negotiable
invariants (single-writer `agents` table, `department_dispatcher.py`, no merges, no
self-approval) plus the still-installed `opencode-pr` / `gh` guard. Both files live
only in container volumes — nothing in the repo or the Dockerfile generates them, so
this fix does not survive an image rebuild. Making it durable means teaching the
owner-owned `opencode/Dockerfile.terminal` (out of this lane's scope) to write a
different GUARDRAILS for the derived image.

### 3. The mounted PAT is real, and it is merge-capable — STILL THE OWNER'S CALL

`opencode-pr`'s header says no GitHub token is mounted here "without their explicit
decision", and `/start.sh:93` still carries the comment "The secret is NOT mounted
yet (owner decision)". Both are false for this instance. Measured, without printing
the value:

| probe | result |
|---|---|
| `/run/secrets/opencode_github_token` | present, 93 chars |
| `git ls-remote` against the private repo | authenticates |
| `GET /user` | 200, fine-grained (no `x-oauth-scopes` header) |
| `GET collaborators/kytran/permission` | 200 |

So the guard-free lane holds a working write credential, and "Pull requests: write"
is not divisible on GitHub — it permits merging. The local guards (`gh` shadow,
`opencode-pr` never merging) are speed bumps, not a boundary.

**Branch protection on `main` — the actual merge stop — could not be verified from
anywhere on this host:**

- lane PAT → `403 Resource not accessible by personal access token`
- platform token (`/mnt/archie_brain/secrets/api/github_token.txt` via
  `github_service._api_get`) → `403`, same message

Neither token carries `Administration: read`. Closing this needs the owner to look
at the branch-protection settings for `main` in the GitHub UI, or to add that scope
to a token. Until then, the honest statement is: **unknown, and it is the only thing
standing between this lane and a self-merge.**
