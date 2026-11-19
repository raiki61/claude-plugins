---
name: learn-target-conventions
description: Learns the target repository's own conventions from its primary sources (README, contribution guide, lint and CI settings, nearby code) before applying general review points, and says what could not be found. Use when starting a review in an unfamiliar repository, or when asked "what are this project's house rules". Not for separating recorded policy from code comments.
---

# Learn the target's own conventions from its primary sources

**Core rule: do not copy the target's conventions into the review rules. The moment you write them there, they become a copy of the canonical source and stay stale while the repository changes. Learn them from the target's primary sources before you apply the review points.**

## Pitfalls (read first)

- **Silence reads as "none".** Say explicitly what you could not pin down ("could not identify; looked in: ...") and mark what you filled in by inference as inferred.
- **What the code near the diff actually uses is the standard,** not the ideal written in a document. If the two disagree, that itself is a finding.
- **Where a lint, formatter, or type check already fails (goes red) whenever the convention is broken, only confirm that the check currently passes (is green).** Do not check that convention again by hand or by a model: it finds nothing more.
- **Carried facts are references only.** The way this kind of hand-over breaks is that a carried fact puts on the face of an established fact.
  - Do not freeze it as a constraint. "I read it that way in the last review" is not a ground. Re-read when the settings, manifest, or CI definition changed.
  - Do not hand it to a role that doubts from zero. Giving the learned facts to a context-blind grader or to a role that derives the ideal solution from the purpose alone breaks the isolation and lowers the judgment to one that takes "this repository's way" as given. Do not mix facts from earlier reviews into a doubting role's input.

## Steps

### Where to read (use what exists; treat what does not as absent)

- **README, contribution guide, documents**: architecture boundaries, dependency policy, development flow.
- **Lint, formatter, and type-check settings**: conventions enforced by machine.
- **Package manifest**: the language, framework, and test defaults (what need not be written).
- **CI definition**: what is gated.
- **The code near the diff**: the actual standard mechanisms (internationalisation, settings loading, error classification, dependency injection, logging).

### Carrying what you learned

You may carry the facts you learned to later reviews (no need to re-read for every review; when the primary-source files did not change, carry the earlier learning over).

## Done when

- Every source above was read, or marked as absent.
- What could not be identified says where you looked, and what was inferred is marked as inferred.
- No learned fact was given to a role that must doubt from zero.

## How to report

For each source: what you learned from it, or "could not identify (looked in: …)". Mark what is inferred. Name any disagreement between a document and what the code near the diff actually uses as a finding.

## Example

Input: start reviewing a repository you do not know; it has a README and lint settings, and no CI definition.

Reply: README: handlers do not import the storage layer directly. Lint settings: import order is enforced, so only its green is confirmed. CI definition: could not identify (looked in: the repository root and its hidden folders). Code near the diff: errors are classified by a shared helper; the README names a different one — a finding.

## Works well with

- A view that reviews a change's implementation and design, after the target's conventions are known.
