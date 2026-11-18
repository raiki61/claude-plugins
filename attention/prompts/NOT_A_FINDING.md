---
form: list
# What does not count as a finding (design section 3, W10). Given to the finders (W4, W6) and to both W10 refuters.
# Written for this repository, not copied. Pattern from bug-hunt.js FALSE_POSITIVE_DOCTRINE, which goes to every
# finder and every refuter: https://github.com/vnovick/itervox/blob/d4f5e2e2daa6abb230fd5646e642151847b19f45/.claude/workflows/bug-hunt.js#L36-L58
# (Apache-2.0). Kinds of rejection also from hexDAG, plimeor and cc-debate (see the design section 14.7 table).
---
- The code does not do what the claim says: read the body of the function or the check, not its name, its signature or a comment about it.
- It is already prevented elsewhere: before claiming a missing check or a wrong value, read every caller and every place that writes the value. A guard upstream, a type, a schema or an invariant that makes the case impossible leaves nothing to report.
- No real input reaches it: name the input or state the system actually receives and the path from it to the line. Without that path it is not a finding.
- It is what the base version intends: its rule documents, tests or documented behaviour ask for exactly this (this PR's own reasons do not count; see the shared rules).
- This PR did not bring it: it is unchanged at the base, and this PR neither adds it, makes it reachable, nor builds on it. Say it predates this PR instead of reporting it as this PR's problem.
- It rests on a stale view: every claim about a file comes from reading that file in this run (PR head, or the base with the base prefix), not from memory or an earlier version. A path claimed missing is checked first.
- It is a taste no rule document at the base asks for.
- It is a guess: "might", "could" or "probably" with no traced input or state and its result.
- It is a record of the past (a changelog entry, a decision record) faulted only for describing what happened then.
- Its weight is inflated: how serious it is follows from what a person would see in the concrete scenario, not from the wording.
