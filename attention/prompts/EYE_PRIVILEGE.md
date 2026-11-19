---
vars:
  signals: list   # stage 0 identitySignals: "<path>:<line> <text>"
---
Least privilege. Lines this PR adds that set an identity or a permission (found by the prep stage):
{{signals|bullets}}
For each new identity operation, list the least permission it needs (from the platform's primary documentation) and the permission the PR grants. A grant wider than the need, a secret exposed to a step that does not use it, or a token with a scope the operation does not use is a finding.
