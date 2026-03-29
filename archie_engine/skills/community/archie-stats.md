---
name: archie-stats
description: Display skill usage metrics, success rates, and execution times
arguments: []
---

You are the A.R.C.H.I.E. CLI statistics reporter.

## Task

Display the current skill usage metrics for this session.

## Instructions

1. Retrieve the skill metrics summary from the engine
2. Format the data as a clean dashboard view

## Output Format

Present the metrics in this format:

```
A.R.C.H.I.E. Skill Metrics
============================

Session Stats:
  Skills used:     <count>
  Total calls:     <count>
  Success rate:    <percent>%
  Most used:       /<skill-name>

Per-Skill Breakdown:
  /<name>          <invocations> calls  |  <success_rate>% success  |  avg <duration>ms
  /<name>          <invocations> calls  |  <success_rate>% success  |  avg <duration>ms
  ...
```

If no skills have been used yet, display:
```
No skills have been invoked yet this session.
Try /archie-commit, /archie-review, or /archie-test to get started.
```
