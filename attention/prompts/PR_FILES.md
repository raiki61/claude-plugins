---
vars:
  diff: text
  excluded: list
  priorDiff: text?
  priorHead7: text
  thread: text
---
- Diff file (commit list, --stat, -U10 diff): {{diff}}{{#if excluded}} (lock files left out of the body, still in --stat: {{excluded|join:", "}}){{/if}}
{{#if priorDiff}}
- Diff since the previous run's head {{priorHead7}}: {{priorDiff}}. What it touches was added after the previous run.
{{/if}}
- PR conversation (body, comments, reviews): {{thread}}
