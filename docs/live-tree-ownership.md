# Live tree ownership: why files become unwritable, and the durable fix

**Applies to:** `/mnt/archie_brain` (the shared A.R.C.H.I.E. repo, bind-mounted
into many containers).

## Symptom

The operator account (uid 1000 — `kytran` on the host, `node` in the agent
lane containers) suddenly cannot write a file it could read seconds earlier:

```
error: unable to unlink old 'platform_v2/tools/brainstorm/routes.py': Permission denied
```

It is not a permissions *change* — the file is newly created, owned by root, and
was never writable by uid 1000. The usual reflex is `git update-index
--skip-worktree` to hide it. That hides the symptom and creates a second
problem, so don't.

## Cause

`archie_platform` runs as **uid 0**. It has no `user:` key in
`docker-compose.yml` (confirmed with `docker exec archie_platform id`), while
`archie_opencode_terminal` correctly declares `user: "1000:1000"`.

It bind-mounts tree subdirectories `:rw`, including:

```
- ./.git:/mnt/archie_brain/.git:rw
- ./repos:/mnt/archie_brain/repos:rw
- ./scripts:/mnt/archie_brain/scripts:rw
- ./host_commands:/mnt/archie_brain/host_commands:rw
- ./.claude/rules:/mnt/archie_brain/.claude/rules:rw
- ./website/kytranempowerment.com/data:/mnt/archie_brain/website/kytranempowerment.com/data:rw
- ./website/kytranempowerment.com/assets/portraits:/mnt/archie_brain/website/kytranempowerment.com/assets/portraits:rw
```

Every file the platform writes there is created `root:root`. About 41k entries
in the tree are in that state (`repos/` ~35k, `platform_v2/` ~4.4k, `.claude/`
~1.4k, and 3 inside `.git` — which can wedge *any* git operation, not just
`checkout`).

The nastiest secondary effect: a pre-commit hook that stashes the working tree
may partially fail, reverting working copies while leaving the index staged.
That looks like "my staged changes vanished" and can silently lose work.

## Fix

`scripts/fix-live-tree-ownership.sh` (check-only by default):

```bash
sudo ./scripts/fix-live-tree-ownership.sh                 # diagnose
sudo apt-get install -y acl                              # one-time, if setfacl missing
sudo ./scripts/fix-live-tree-ownership.sh --apply-acl     # durable fix
```

Requires the `acl` package. Idempotent; re-run any time.

### Why ACLs and not `chown`

`chown -R 1000:1000` fixes the 41k files that exist now, and the container
recreates the condition on its next write. A **default** ACL is inherited by
every file created in that directory afterwards, so it holds for new files too.
It also leaves root's access untouched — which matters, because
`platform_v2/Dockerfile` notes that TTS triggers a **runtime pip install**, so
`archie_platform` genuinely needs root. ACLs fix the operator's access without
touching the container's privileges.

Host and lane are both uid 1000, so one ACL entry covers both.

`secrets/` is pruned from every operation. The lane is granted no secrets by
policy; `secrets/` is mounted `:ro` into the platform container so it gains
nothing here, and an explicit `u:1000` entry would hand the lane container read
access to secret files.

### Verifying

The script's write probe is the real test — it samples foreign-owned files and
asks whether uid 1000 can actually write them, rather than trusting `ls`:

```
== Write probe (the real test) ==
probed 40 foreign-owned files as kytran
NOT writable by kytran : 0
VERDICT: access is already in place (ACLs present or ownership aligned)
```

**Do not verify with `test -w`.** Once ACLs are in play it reports false
negatives — on a `root:root` 755 directory carrying an access ACL, `test -w`
said "not writable" while a real write succeeded (ACL mask artifact). The script
therefore probes by opening each file in append mode, which requires write
permission but writes nothing:

```bash
sudo -u kytran python3 -c 'import sys; open(sys.argv[1],"a").close()' FILE
```

Verified on 2026-09-26 after the fix, by append-open on all 35,772 foreign-owned
regular files: **32 unwritable**, all in platform-owned runtime output —
31 in `host_commands/completed/` (gitignored via `.gitignore:141`, zero tracked
files) and 1 in `kytran-server-manager/data/postgres/pg_logical` (live Postgres
internals). Nothing the development workflow touches is affected.

**Known limitation.** A root process that creates a file and then calls
`chmod(644)` on it rewrites the ACL **mask** to `r--`, which nullifies the
`u:1000:rw` entry while leaving the mode string looking like a plain `644`. That
is why the platform's `host_commands/completed/` results keep reverting: the
inherited grant is stripped on contact. Files created without an explicit chmod
— which is how git, editors and build steps write — inherit correctly. The
residual is therefore cosmetic for the dev workflow; re-running `--apply-acl`
restores those files until the platform's next write. Leave
`kytran-server-manager/data/postgres/` alone rather than relaxing permissions on
a live database directory.

## Keeping the residual clean

The 31 `host_commands/completed/` files revert on every platform write, so
`scripts/archie-live-tree-acl.cron` puts the grant back hourly. It is scoped to
that one directory on purpose:

```bash
sudo cp scripts/archie-live-tree-acl.cron /etc/cron.d/archie-live-tree-acl
sudo chown root:root /etc/cron.d/archie-live-tree-acl
sudo chmod 644 /etc/cron.d/archie-live-tree-acl
```

Install it **without** the `.cron` suffix: Debian's cron silently ignores
`/etc/cron.d` entries whose names contain a dot. It runs with `--quiet`, so a
successful run mails nothing and you are only told when something is wrong. The
script refuses `--path secrets` and refuses a resolved target uid of 0, so a
misconfigured timer cannot grant or chown to root by accident.

## Considered and rejected

**`user: "1000:1000"` on `archie_platform`.** Attractive, but the runtime pip
install for TTS needs root, so this is not a safe blanket change — it would need
the Dockerfile restructured to install TTS deps at build time first. Also
`docker-compose*` is in `blocked_globs` for the agent lanes, so neither lane may
make this change; it is an owner/host decision.

**Running the agent lane as root.** Would make the symptom disappear and would
also remove the boundary that keeps a lane from damaging the tree. No.

## Related

- `scripts/fix-live-tree-permissions.sh`'s sibling, the one-off repair used on
  2026-09-26 for a specific root-owned file. This document covers the general,
  recurring case; that script is the narrow hammer.
