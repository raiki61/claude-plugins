---
vars:
  items: list   # one item per new question: "<id>: <first line of the question> | <where, or ->"
  known: list   # the keys of the questions already in the tree
---
New questions (id: question | where):
{{items|bullets}}

Questions already in the tree (keys):
{{known|bullets}}

Group the new questions that ask the same thing (even when worded differently) into clusters. For each cluster give key (a short canonical wording; if it asks the same as a question already in the tree, use that existing key exactly), question (the wording to dig) and members (the ids, comma-separated). Put a question in dropped only when it does not need digging at all, with why. Every new id must appear exactly once, in one cluster or in dropped.
