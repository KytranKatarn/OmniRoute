# Opencode guard-free terminal — spec, part 6 of 6: what is actually known about `main` protection

**Part 6 of 6.** Index: [2026-09-27-opencode-guard-free-terminal.md](2026-09-27-opencode-guard-free-terminal.md).

---

## Correction — what is actually known about `main` protection

Earlier revisions of this spec, and the dry-run text, said protection was
"unverifiable" and told the reader to check it themselves. That was wrong in a
way that mattered: the `403` came from hitting the **admin-only**
`/branches/main/protection` endpoint, not from protection being absent. Measured
2026-09-28 with both host tokens:

| fact | value | how |
|---|---|---|
| `main` protected | **yes** (`protected: true`) | `GET /branches/main` — repo read, not admin |
| repository rulesets | **0** | `GET /rulesets` |
| required status checks | **enforcement off** | `protection.required_status_checks` in branch metadata |
| `required_approving_review_count` | **unknown** | needs `Administration: read`; REST `403`, GraphQL `404` |
| `enforce_admins` | **unknown** | same |

History is the uncomfortable part: the last 10 merges into `main` carried **zero
reviews**, all authored by the owner account. So a review-free merge has been
possible in practice. That is consistent with admin bypass, with
`enforce_admins=false`, or with a review requirement that simply is not stopping
this account — and `main` is `mergeable_state: blocked` for #3504 right now, so
*something* is being enforced at the moment.

The honest statement, replacing the earlier one: `main` **is** protected and the
residual risk is **not** "unprotected branch" but "cannot tell whether the
credential this lane holds clears the remaining requirement". Only the owner can
close that, by reading the rule in the GitHub UI, or by granting
`Administration: read` to a token used only for audit. Dev HQ #7026.

---
