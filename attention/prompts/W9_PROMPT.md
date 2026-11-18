---
vars:
  prFiles: text
  structure: text
  leaves: list   # one item per decided leaf: "<id>: <first line of the question> => <answer on one line> | <evidence locations>"
  diffs: list    # "<difference> => <decision>"
  limit: text    # how many fixes and groups at most
---
{{prFiles}}

Structure of the system:
{{structure}}

Decided leaves of the question tree (id: question => answer | evidence):
{{leaves|bullets}}

Differences from the general structure and their decisions: {{diffs|join:"; "|or:"(none)"}}

1. fixes [s14.1][s14.2]: Fix options built from these leaves, choosing in this order: "remove" (make what is in two places from one place, remove the premise), then "type" (a schema or type makes a drifting value impossible to write), then "tool" (a ready-made tool), then "self-made". If a higher rung prevents it, do not offer the lower rung. [s14.3] Rules you write yourself on a ready-made tool count as self-made. For each fix, worldSolution [s13.1]: how the world solves the same (the URL of an official primary source you checked), or "none" and the words you searched; leaves: the leaf ids it rests on, comma-separated.
2. groups [s12.1][s12.2]: Groups among the roots: fixes or leaves that one fix settles together ("one-fix"), and a fix that breaks another root's answer ("conflict"). Members are fix numbers (F1, F2 ... in the order of your fixes) and leaf ids, comma-separated. Check each group really holds. If you looked and found none, return no groups.
3. outside [s12.3][s12.4]: Search open issues and PRs that plan to build the same environment, mechanism or tool, with `gh issue list --state open --search <words>` and `gh pr list --state open --search <words>` (words: the mechanisms and the names of the environments they need). For each hit, say whether we can ride their environment or they can use our parts. searched: the words you searched (always).
At most {{limit}} fixes and groups together; put the most important first.
