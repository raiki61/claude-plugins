---
vars:
  standards: list   # W1's standards
---
Premises of the standards this PR builds on: {{standards|join:", "}}
For each pair of them, find where their premises meet in this PR: resending and retries, re-running a step, idempotency, ordering, timeouts, who owns a state. Name each place where one standard's premise breaks the other's, with the primary source of each premise.
