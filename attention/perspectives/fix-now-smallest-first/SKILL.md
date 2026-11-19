---
name: fix-now-smallest-first
description: "Decides whether a review finding is fixed now or deferred, by cause, and picks the prescription from the smallest up: delete, reuse, narrow the claim, adopt an outside solution, and only then build. Use when asked \"should we fix this now or later\" or how big the fix should be. Not for judging the size of a change already written."
---

# Fix now, and start from the smallest prescription

**Core rule: what this change introduced or exposed is collected in this same change. And a larger prescription may be taken only when one sentence says why each smaller one falls.**

Words used here:

- **A review cycle**: one pass of review, fix, and review again.
- **The grader**: the reviewer who decides how each finding is handled, separate from whoever writes the fix.
- **The frozen purpose**: the purpose and scope fixed for this change when it started.
- **A dead developer path**: a route by which a developer finds and understands the code (names, structure, documents, error messages) that no longer leads them right — it misleads, or leads nowhere.
- **The ledger of questions**: the record where deferred questions are kept so they are not lost.
- **The minimality check**: the check that the fix is no larger than needed and that nothing inside the purpose was let go.
- **The check for piled-up ad-hoc fixes**: the check that a fix solves the cause instead of adding one more patch on top of earlier patches.

## Pitfalls (read first)

- **Do not make deferral the default.** Decide by the cause of the problem. A separate issue is right only for a problem that already existed and is unrelated to this change. Context is freshest now; separate issues tend to rot; deferral leaves an unfinished change.
- **Never justify deferring a fix, or skipping verification (re-grading, re-review), by the judge's convenience** (cost, trouble, "it never ends"). Decide only by a structural reason. That decision is made by whoever grades, not by whoever carries the work (cut the conflict of interest). What you fix now still goes through the check for piled-up ad-hoc fixes.
- **A comment is the last resort.** It can be written on the spot and turns nothing red, so it easily becomes the default fix; left alone, only comments pile up — more to read, path still dead.

## Steps

Read "Fix now or defer" to decide whether a finding is fixed now; read the other three subsections to choose its prescription.

### Fix now or defer

- The default is **do now** (deferred debt rots, and the next implementer falls into the same rut).
- A suggestion may be deferred to a separate issue or change only when you can name one structural reason: an unresolved design decision, a different scope or subsystem, or low reversibility that needs agreement.
- When collecting an existing defect that this change exposed would swell beyond the frozen purpose, the grader may **apply** for an exception: collection stays the default for everything else; only this one defect is dropped into deferral and put on the ledger of questions. The review that puts the defect on the ledger does not ask a person about it. The grader of the next review re-examines it, and the work stops to ask a person only when all the work that can go on without an answer has run out. The grader only applies; whether the defect is really deferred is decided by the person who is then asked, not by the grader. Whether something inside the purpose escaped is checked by the minimality check.
- Surfacing an unrelated large improvement as a suggestion is a separate axis and is fine.

### Order of prescriptions

For a must-fix or do-now finding, list prescriptions in this order:

1. **The zero prescription**: solve it by deleting; solve it with one existing flag or mechanism; solve it by narrowing the claim.
2. **Adopt the world's solution**: cite from primary sources how the world solves the same problem (standard specifications, well-known open-source software, official documents), and take it if you can. A question the world's solution settles is not a fork in the design: do not send it to a person; adopt it as the prescription. Ask a person only when the world's solution does not settle it (when you can say what is stuck or what doubt remains).
3. **Build a new mechanism**: only with sources showing why the world's solution is absent or unusable. If you cannot write that, do not build it.

(Seen once: a mechanism received a count as a free one-line text written by an AI role, and guarded that text with a home-made list of allowed strings. Three review cycles in a row, a gap came through a different entrance. The OWASP OS Command Injection Defense Cheat Sheet ranks "separate data and command by structure" above "validate the string"; taking that — receiving the count as a structured value — would have made the allow-list unnecessary.)

### A new mechanism is design work

- Building a new mechanism or widening a shared surface (a package, factory, or common setting used by several consumers) is design work, not a fix; do not implement it without this list. When there are several candidates and choosing needs judgment, it is an unresolved design decision (a structural reason to defer).
- The defect itself cannot be left, so **withdrawing the change that brought the defect, and making it trackable, is also a zero-prescription candidate.** Leaving a defect the change introduced is not allowed; withdrawing the change that introduced it is collection, not deferral.
- (Seen once: as a review fix, a conversion middleware was added to a shared factory; the design decisions — what it catches, where it applies, which existing flag — then burst out one per review cycle. Listing the zero prescription (withdraw the mechanism and open a tracking issue) first would have finished in one cycle.) A review cannot make design decisions; passing a mechanism that skipped design makes the review take over the skipped design work one question per cycle.

### Fixing a dead developer path

Choose in this order:

1. **Structure**: split, move, **express it in a type so the invalid state cannot be made**.
2. **Naming.**
3. **Bind it mechanically**: make violations turn a test, a type check, or a lint red, and carry the intent in the test's name.
4. **A comment** (a why comment, a docstring).

- A comment may only say why other options were rejected, or document a surface called from outside (a public API). A comment that says "what it does" is a sign that the structure or the name is already dead: have a reader without context read with the comments stripped, and it shows that the comment carried no information (delete a comment whose removal still leaves a correct explanation).
- If you cannot say in one sentence why 1–3 cannot work, do not settle for 4 alone.
- **If 3 makes an existing check always true, that is breaking the check, not a mechanism.** If structuring makes some test necessarily green, either delete that test or drop the structuring and keep the check — choose one; do not keep both.

## Done when

- Each finding is do now, or deferred with one structural reason named — never by cost or convenience.
- Its prescriptions are listed from the zero prescription up, and every larger one taken has one sentence on why each smaller one falls.
- A new mechanism is taken only with sources showing why the world's solution is absent or unusable.
- A dead path is not fixed by a comment alone unless one sentence says why structure, naming, and a mechanical check cannot work.

## How to report

For each finding: do now or deferred (with the structural reason when deferred); the prescriptions listed in order; the one taken; and, for each smaller one passed over, the sentence on why it falls.

## Example

Input: this change gave a function named for checking input a new side effect: it also writes to disk. Developers misread it. The proposed fix is a comment saying it writes.

Reply: Do now — this change introduced it. Prescriptions: 1 structure: move the write into its own function; 2 naming: rename the function; 3 a test that fails if checking writes; 4 the comment. Take 1: nothing stops the split, so the comment alone is not enough.

## Works well with

- A separate review perspective (another guide like this one) that sets the bar a review finding must clear before it is raised, including when it must be fixed.
