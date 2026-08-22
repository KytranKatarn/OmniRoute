# A.R.C.H.I.E. Code CLI — see the canonical README

The real README lives in the product's own repository:

**https://github.com/KytranKatarn/archie-code** → `README.md`

## Why this file is a pointer and not a copy

It used to be a full 97-line duplicate of that README, referenced by nothing. The
duplication had already caused a real defect: the Phase 4.4 branding pass
(`39155c01b`) corrected `ARCHIE` → `A.R.C.H.I.E.` **here**, on the orphan, and never
reached the README people actually read on GitHub. The private copy ended up with 5
dotted references and the public front page with 1.

A duplicate that nothing imports gets edited by whoever greps for it first, and drifts
from the file that matters. Fixed in archie-code PR #42; replaced with this pointer so
the next pass cannot repeat it.

## Working on archie-code from here

`archie-code` is a SEPARATE repository. `/mnt/archie_brain/archie-code` is a **symlink**
to `/mnt/standalone/archie-code`. Work it from a normal `/mnt/archie_brain` session —
never launch a session inside it, since memory and config are keyed to the launch path
(`.claude/rules/multi-repo.md`).
