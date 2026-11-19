---
name: citation-provenance
description: Checks that the grounds a change cites for itself, such as "the source of truth is X" or "this was agreed", existed before the change, catching grounds the change added itself. Use when a change or its description justifies itself by a convention, a source of truth, or an outside agreement. Not for checking a change against earlier recorded decisions.
---

# Check where the grounds a change cites come from

**Core rule: a ground the change adds itself is no ground. For every claim of the form "the source of truth / the convention / the agreement is X", check that X existed before the change.**

## Pitfalls (read first)

- **Look for the claims in all three places**: the body of the diff, the pull request description, and the docstrings.
- **Check against the version before the change**, not the current one — for example by searching the history of the base for the string that defines X.
- **A circle is evidence, not a verdict.** When the diff cites as grounds something the diff itself adds, write the proof: the place in the diff that adds X, and the result of the command you ran.
- **An agreement with an outside party** (another team, another system, an upstream source) that leaves no trace before the change is an unconfirmed premise, not a fact.
- **Do not break the real working tree.** Make any copy in a fresh temporary directory outside it.

## Steps

1. Extract every claim of the form "the source of truth / the convention / the agreement is X" from the body of the diff, the pull request description, and the docstrings.
2. For each claim, check whether X existed in the version before the change.
3. For each circle, write the proof: the place in the diff that adds X, and the result of the command you ran.
4. Mark each claimed outside agreement with no trace before the change as an unconfirmed premise.

## Done when

- Every claim from the three places has a row with whether X existed before the change and how you checked.
- Every circle carries its proof.
- If you could not check, that is said with the reason, instead of reporting that nothing was found.

## How to report

One row per extracted claim: the sentence of the claim, whether X existed before the change (yes or no), and how you checked it and what you found. Say whether any circle was found, and how many. If you found nothing, say what you looked at; if you could not check, say so and why.

When you name a place in a file, give the line number in the current file, not a line in the diff: lines of a diff are not lines of the file, and a person cannot open that place. Open the file and confirm the line before writing it; if you cannot, give the path with a function name or similar instead of a line number.

## Example

Input: the pull request description says "The convention is that config keys are lowercase (see the style guide)". The same diff adds that line to the style guide.

Reply: Claim "The convention is that config keys are lowercase" — existed before the change: no. Searched the history of the base for "lowercase" in the style guide: no hit; the line first appears in this diff's addition to the style guide. Circles found: 1.

## Works well with

- A set of rules that keeps the reviewed repository's own names and text out of queries sent to outside services (web searches, fetched URLs).
