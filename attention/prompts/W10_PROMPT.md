---
vars:
  prFiles: text
  quoted: flag        # true for a leaf or a smell answer (it has its own quotes), false for a fix option or a group
  trace: flag         # true for the second refuter of a leaf or a smell answer (builds the concrete scenario)
  notAFinding: list   # the NOT_A_FINDING items
  text: text          # one of W10_LEAF, W10_SMELL, W10_FIX, W10_GROUP
# The two refuters of a leaf or a smell answer and their lenses (false positive, concrete failure scenario) follow
# bug-hunt.js: https://github.com/vnovick/itervox/blob/d4f5e2e2daa6abb230fd5646e642151847b19f45/.claude/workflows/bug-hunt.js#L208-L241
# (Apache-2.0, LICENSE at that commit). Copied: "by reading the actual code and its context - callers, guards upstream,
# types or invariants that make the case impossible", "Construct the CONCRETE failure scenario ... exact input or state,
# then the wrong output". Changed: lower case, "the claim" instead of "this", the three verdicts instead of refuted
# true/false, the scenario field, and the trace lens also builds the counter-case of an answer that says something holds.
---
{{prFiles}}

{{#if trace}}
Construct the concrete scenario for the claim below: exact input or state, then what the code does with it. Read the lines it cites and trace them. If the answer says something is wrong, build the failure: exact input or state, then the wrong output, error or lost data. If it says something holds, try to build the case where it does not hold. A problem with no concrete failure scenario is not a finding.
problem: true when the answer below says something in the PR is wrong (a defect, a risk or a smell), false when it says nothing is wrong or that it found nothing. It describes the answer, not what your trace found.
verdict: "stands" when the scenario you traced matches the answer (write it in scenario: the input or state, then the result), "falls" when the trace contradicts the answer, or the answer claims a problem and no concrete failure scenario exists (say why in reason and give evidence), "unverifiable" when reading cannot decide it (say in reason what would have to be run; it stays "unverified", not refuted).
{{else}}
Try to prove the claim below is a false positive, by reading the actual code and its context: callers, guards upstream, types or invariants that make the case impossible. {{#if quoted}}First check whether the quotes really support the answer: is the claim actually supported by the quote, or is it an overreach or a misread? Then check the claim itself in the code and the sources.{{else}}It has no quotes of its own: check the content at the world-solution URL and whether the quotes of the leaves it rests on support it.{{/if}}
verdict: "stands" when you could not refute it, "falls" when it is wrong (give evidence), "unverifiable" when you cannot check it (say why in reason; it stays "unverified", not refuted).
{{/if}}

A claim of a problem that is one of these falls; name which one in reason:
{{notAFinding|bullets}}
Do not let a claim fall only because it is small, a matter of style, or one you would not raise: only one of the items above or evidence that it is wrong makes it fall.

{{text}}
