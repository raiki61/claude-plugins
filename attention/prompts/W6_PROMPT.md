---
vars:
  shared: text       # the W6_SHARED text
  id: text           # the node id
  paths: list        # one item per path from a root: "Path <n>:" and one "- Q: ... | A: ... | assumed: ..." line per ancestor
  parentLocs: list   # the locations the parents read
  where: text        # where to look first; empty when not given
  question: text
  lenses: text       # the lens texts for this node's root class (LENS_TABLE.W6), or ""
  again: text        # for the redig stage: the earlier "unverified" answer and what it said would decide it; "" otherwise
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

{{lenses}}
{{#if again}}

This node was answered "unverified" before. That answer, and what it said would decide it:
{{again}}
Answer it once more, using that as the lead. Do not split it: return no children and a status other than "split".
{{/if}}

Your question (decide this here; hand to children only questions whose answer would change yours):
{{question}}
