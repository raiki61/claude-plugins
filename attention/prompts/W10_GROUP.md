---
vars:
  kind: text
  members: text
  why: text
  fixes: list   # "<fix id> <first line of the fix>"
---
Group ({{kind}}): {{members}}
Why: {{why}}
Fixes: {{fixes|join:"; "|or:"(none)"}}
