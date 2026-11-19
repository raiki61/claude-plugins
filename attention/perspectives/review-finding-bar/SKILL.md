---
name: review-finding-bar
description: "Sets the bar a code-review finding must clear before it is raised: a strict test for must-fix, a stated mechanism, a measurement or a mark that it was not measured, and a self-refutation. Use when grading a drafted finding, or when asked \"is this finding solid enough to raise\". Not for deciding when or how a finding gets fixed."
---

# The bar a review finding must clear

**Core rule: a claim is free and verification is costly. A reviewer who has the means to verify must verify before raising — submit only the findings you could not kill yourself.**

## Pitfalls (read first)

- **Refute your own finding before you submit it.** If you cite a rule, read whether its conditions really apply and what the surrounding code actually does. (Seen once: four reviewers independently raised the same formatting finding without reading the rule's condition clause; all four were out of its reach, and one step of reading the clause would have killed each.)
- **Do not move the cost of verification downstream** to whoever diagnoses or implements. An unverified claim is not a funnel; it is negligence.
- **A subjective "hard to read" alone is not "must fix".**
- **Low-confidence findings and existing problems outside the change's scope stay at "suggest" or below.**

## Steps

### Labels

Give each finding one label:

- **[block]**: must fix. It meets all three: (1) the fact is confirmed (pinned down by code or behaviour, not a guess); (2) the harm is concrete (broken function, security, data corruption, performance loss, or a sentence can say that a skilled developer actually misread it or that a path is dead); (3) it should be fixed in this scope (tracking it in a separate issue is not enough). Through the readability route (misreading, dead paths), it is [block] only when you can reproduce how it is misread with a concrete example and name which element of naming or structure causes the misreading.
  - Judge condition (3) by cause: a problem this change introduced or exposed is collected in this same change; a separate issue is right only for a problem that already existed and is unrelated to this change.
- **[suggest]**: a better implementation exists but is not required.
- **[nit]**: minor (style, naming taste).
- **[question]**: asking about intent.
- **[info]**: sharing information, not a finding.

### What a finding carries (a reviewer who can read and run the repository)

- **Mechanism**: one sentence on the causal chain in the code (not just pointing at the symptom).
- **Measurement**: run what can be run and reproduce it. If you cannot run it, mark it "unmeasured" and raise it as a hypothesis.
- **Self-refutation**: done before submitting (see the pitfalls).
- **False-positive estimate**: one line on when this finding would be wrong.

A context-blind reviewer (an isolated sensor with no means to verify) is outside this bar: it raises observations as hypotheses, and verification falls to whoever diagnoses. **A sensor's shallowness is its job, not a defect**: shallow, orthogonal eyes catch layers the deep eye cannot see.

### Questions every review asks

- Does the implementation follow the change's purpose? Is the before/after difference sound?
- Security: leave a detailed vulnerability scan to a dedicated security review; in a review, stop at obvious missing input validation and leaks of sensitive data.
- The ripple to files that depend on what is reviewed.
- Whether tests need to be added.
- **The developer path**: do the README, documents, sample environment files, error messages, and folder structure leave a first-time developer lost?
- Is the code style consistent with the other files?
- **Ask where a finding came from**: even for a finding you will not act on, analyse why it arose. If the cause is readability, naming, or a dead path, fix the readability side even when the logic is right. What a skilled developer misreads, future developers will misread too.

## Done when

- Each finding has one label, and every [block] meets all three conditions, with condition (3) judged by cause.
- A reviewer who can verify has, for each finding, the mechanism, a measurement or an "unmeasured" mark, the self-refutation done, and the false-positive estimate.
- A context-blind reviewer has raised its observations as hypotheses.

## How to report

For each finding: its label and what is wrong. A reviewer who can verify adds the mechanism, the measurement (or "unmeasured", as a hypothesis), and the false-positive estimate.

## Example

Input: a reviewer who can run the tests sees that a function changed in this diff now returns early on a lookup error, before the line that closes the file it opened.

Reply: [block] The file is left open on the lookup-error path. Mechanism: the early return added in this change skips the close. Measurement: ran the error path; the count of open handles grows by one per call. Self-refutation: checked the callers; none closes the file. False positive if: a caller wraps the call in a scope that closes it. Condition (3): this change introduced it, so it is fixed here.

## Works well with

- A view that decides whether a finding is fixed now or deferred, and which prescription to choose, starting from the smallest.
