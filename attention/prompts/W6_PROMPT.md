---
vars:
  shared: text       # the W6_SHARED text
  id: text           # the node id
  paths: list        # one item per path from a root: "Path <n>:" and one "- Q: ... | A: ... | assumed: ..." line per ancestor
  parentLocs: list   # the locations the parents read
  where: text        # where to look first; empty when not given
  question: text
---
{{shared}}

## Your node {{id}}

Path from the root (questions, answers and what was assumed; do not re-decide what ancestors decided, but you may doubt their premises):
{{paths|join:"\n"|or:"- (this is a root)"}}

Where the parents looked (locations only):
{{parentLocs|bullets}}
{{#if where}}

Where to look first: {{where}}
{{/if}}

Your question (decide this here; hand to children only questions whose answer would change yours):
{{question}}
