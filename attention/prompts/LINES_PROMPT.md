---
vars:
  prFiles: text
  lenses: text        # LENS_TABLE.Lines
  items: list         # one item per ledger item: "<id> [<findingKind>; <state>; refute: <verdict>] <claim> | at <locations> | cost: <cost> | scenario: <scenario>"
  notAFinding: list   # the NOT_A_FINDING items
---
{{prFiles}}

{{lenses}}

Every finding of the ledger, with the refuters' verdict:
{{items|bullets}}

Look at them all side by side and draw the lines: give every id exactly one entry.
- label: the review label. If the rule documents of this repository (in the shared rules) define review labels, use those; otherwise one of block, suggest, nit, question, info.
- level: "design" when it is something this PR's design decides, "detail" when following a part's specification settles it, "taste" when it is a preference. Only what following a part's specification settles is detail: findings of upkeep, self-made parts and removable lines are choices of this PR's build and are never detail.
- route: "draft" (a review comment to post), "report" (shown to the person only), "fold" (it is the same finding as another id; give that id in into) or "drop". Draft only a design-level finding the refuters let stand ("stands"); a "suspected" or "unverifiable" one is report only. Put the details together: fold the detail findings into one of them, and say in its why where the part's specification is. Drop only a finding the refuters let fall, or one of the items below (name it in rule); "small" alone is no reason to drop:
{{notAFinding|bullets}}
- A problem this PR brought in or brought to the surface belongs to this PR; do not send it to another issue.
- why: one line, the reason for the route. Ask the person (route "report", and say so in why) only when the sources disagree or the finding would undo an earlier decision.
