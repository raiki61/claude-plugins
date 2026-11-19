---
vars:
# The fields every finder (W4 and the lens eyes, W6) fills so the ledger (stage 11) can carry each finding to the
# report: its kind, every place it occurs, and its cost (design attention/docs/my-turn-dig-redesign.md, stages 5 and 7).
---
For an answer that says something in the PR should change:
- findingKind: "breakage" (something can go wrong for a person), "upkeep" (the next change costs more: the same fact in several places, explanation doing the code's work), "self-made" (built by hand where the world has a part), "removable" (lines or parts the purpose does not need), "rule" (against a rule document of the repository), "prior-decision" (undoes a decision already made), "privilege" (more permission than the operation needs), "test" (a test removed without a replacement, or a test double unlike the real thing). For an answer that finds nothing, "none".
- locations: every place the same answer applies to, each as path, line and the exact quote of that line, not only the first one you met. If the same pattern is in three files, list all three.
- cost: for every kind but "breakage", the work it causes, in numbers you counted: how many places hold the same fact, how many lines are kept up, how many lines could go. For "breakage" and "none", "".
