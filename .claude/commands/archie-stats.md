# A.R.C.H.I.E. Session Stats — Token & Context Awareness

Show current session metrics to help plan remaining work within usage limits.

## Step 1: Gather Data

Run `bash /mnt/archie_brain/.claude/hooks/session-stats.sh` to get session metrics JSON.

Then run these git commands:
- `git log --oneline --since="6 hours ago"` — commits this session
- `git diff --stat` — uncommitted changes

## Step 2: Display Stats

Print the following formatted report using the gathered data:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 A.R.C.H.I.E. SESSION STATS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 Session:  [name] ([session_id])
 Started:  [HH:MM] ([Xh Ym] ago)
 Plan:     Max 20x (resets every 5h)
 Model:    Opus 4.6 (1M context window)

 ACTIVITY
 ├─ Messages:     ~[N] exchanges
 ├─ Commits:      [N] this session
 ├─ Files changed: [from git diff --stat]
 └─ Plugins:      [N] active (7 disabled this session)

 CONTEXT WINDOW (estimated)
 ├─ Base overhead:  ~15K (CLAUDE.md + rules)
 ├─ Plugins:        ~5K (reduced from ~25K)
 ├─ Conversation:   ~[messages × 500] tokens
 ├─ Tool I/O:       ~[messages × 300] tokens
 └─ Estimated:      ~[total]K / 1,000K ([%]%)

 PLAN USAGE
 └─ Check: https://claude.ai/settings/usage
   (No local API access yet — Task #1749)

 RECOMMENDATION
 [If elapsed > 3h or messages > 50:]
   "Long session — consider /archie-save checkpoint"
 [If elapsed < 1h and messages < 20:]
   "Fresh session — plenty of room"
 [Default:]
   "Active session — [N] commits shipped"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Step 3: Available Commands

Remind the user:
- `/archie-save` — checkpoint now (commit + save state)
- `/archie-end` — full session close-out
- `/compact` — if context window feels heavy
