---
vars:
  prFiles: text
  trace: flag         # true for the second refuter of a finding or a smell answer (builds the concrete scenario)
  cost: flag          # with trace: the finding is of a kind other than breakage; build the cost scenario instead
  recount: flag       # without trace: the second refuter of a "fine" leaf; recount the premise it rests on
  lenses: text        # the lens texts (LENS_TABLE.W10), or ""
  notAFinding: list   # the NOT_A_FINDING items
  text: text          # the claim: a finding of the ledger, a "fine" leaf or a smell answer
# The two refuters of a leaf or a smell answer and their lenses (false positive, concrete failure scenario) follow
# bug-hunt.js: https://github.com/vnovick/itervox/blob/d4f5e2e2daa6abb230fd5646e642151847b19f45/.claude/workflows/bug-hunt.js#L208-L241
# (Apache-2.0, LICENSE at that commit). Copied: "by reading the actual code and its context - callers, guards upstream,
# types or invariants that make the case impossible", "Construct the CONCRETE failure scenario ... exact input or state,
# then the wrong output". Changed: lower case, "the claim" instead of "this", the three verdicts instead of refuted
# true/false, the scenario field, and the trace lens also builds the counter-case of an answer that says something holds.
---
{{prFiles}}

{{lenses}}

{{#if trace}}
{{#if cost}}
The claim below is a finding of a kind other than breakage (upkeep, self-made, removable, a rule, a prior decision, privilege, a test). Do not look for a failure; construct its cost scenario instead: the next time someone changes the thing it names, how many places and how many lines must change, or how many lines could go. Count them in the real code, and compare with the cost the claim gives.
problem: true when the answer below says something in the PR should change, false when it says nothing should.
verdict: "stands" when your count shows the cost is real (write it in cost: the change, then the places and lines you counted), "falls" when your count contradicts the claim or there is no cost (say why in reason and give evidence), "unverifiable" when reading cannot decide it (say why in reason; it stays "unverified", not refuted).
{{else}}
Construct the concrete scenario for the claim below: exact input or state, then what the code does with it. Read the lines it cites and trace them. If the answer says something is wrong, build the failure: exact input or state, then the wrong output, error or lost data. If it says something holds, try to build the case where it does not hold. A problem with no concrete failure scenario is not a finding.
problem: true when the answer below says something in the PR is wrong (a defect, a risk or a smell), false when it says nothing is wrong or that it found nothing. It describes the answer, not what your trace found.
verdict: "stands" when the scenario you traced matches the answer (write it in scenario: the input or state, then the result), "falls" when the trace contradicts the answer, or the answer claims a problem and no concrete failure scenario exists (say why in reason and give evidence), "unverifiable" when reading cannot decide it (say in reason what would have to be run; it stays "unverified", not refuted).
{{/if}}
{{else}}
{{#if recount}}
The answer below says the PR may stay as it is, and names the one premise that "fine" rests on. Recount that premise against the real thing (the code, the config, an upstream primary source): measure it again yourself instead of trusting the answer. If the "fine" also rests on other premises that hold, do not make it fall.
verdict: "stands" when the premise holds, "falls" when it does not (give evidence; the answer is reopened), "unverifiable" when you cannot check it (say why in reason).
{{else}}
Try to prove the claim below is a false positive, by reading the actual code and its context: callers, guards upstream, types or invariants that make the case impossible. First check whether the quotes really support the answer: is the claim actually supported by the quote, or is it an overreach or a misread? Does the answer's conclusion follow from the evidence the answer itself gives (evidence saying "only an optimization" does not support "it may stay")? Then check the claim itself in the code and the sources. If the answer rests on a claim about the world ("no OSS does this", "upstream cannot", "the tool has no such option"), open the URL of the official primary source and check it; if you cannot open it or it does not say so, the verdict is "unverifiable", not "stands".
verdict: "stands" when you could not refute it, "falls" when it is wrong (give evidence), "unverifiable" when you cannot check it (say why in reason; it stays "unverified", not refuted).
{{/if}}
{{/if}}

A claim of a problem that is one of these falls; name which one in reason:
{{notAFinding|bullets}}
Do not let a claim fall only because it is small, a matter of style, or one you would not raise: only one of the items above or evidence that it is wrong makes it fall.

{{text}}
