---
name: zero-based-design
description: Designs the ideal solution from the purpose and measured constraints alone, without seeing the plan, implementation, or diff, first doubting that the problem exists, and lists it as numbered elements. Use when an independent design is wanted to compare a plan against, or when asked "what would we build from a blank page". Not for designing from premises a person already set.
---

# Design from the purpose alone, before seeing the plan

**Core rule: start from nothing but the purpose and the measured constraints — and before designing, doubt that the question exists.**

Why: a design made after reading the plan, the code, or the history agrees with them. A design made from the purpose alone is a second input that the plan can be compared with, and it catches the case where the whole plan answers a question that did not need asking.

## Pitfalls (read first)

- **You inherit nothing.** Not the fix plan, not the history of the judgment, not the implementation, not the cumulative diff, not the points already settled. What you are given is the original purpose, the measured constraints, the premises a person set, and the person's policy (when there is one).
- **A hypothesis is not a constraint.** A constraint marked as a hypothesis is not taken as given.
- **An unchecked judgment is not grounds.** An earlier review of the purpose may have judged that the stated purpose narrows what was asked. If that judgment has not passed its own check and nobody has recounted its grounds, do not use it as a reason that the purpose cannot be taken as the starting point of an independent design.
- **The change under review does not prove itself.** Lines that the change under review itself added are not grounds for "already met by an existing mechanism"; judge whether the question stands by the state before that change.
- **Do not stop at one launch of the deliverable.** A design that only works the first time is not a design.

## Steps

### 1. Doubt that the question exists

Before designing, ask:

- Does the problem this change solves exist?
- Is it already met trivially by an existing mechanism? (For example, if one deploy is one repository, the repository itself is the identifier, and the question of recording it separately does not arise.)
- Is the work stepping into implementation while the requirement is still undecided?

If the question does not exist, is met trivially, or rests on an undecided requirement, do not design. Give the grounds instead. When the grounds name something real, point to it exactly (a path and a line, or a line range) in the repository as it was when the request was made (the commit the request is based on), so that it can be checked.

### 2. If the question stands, design

- Write the ideal solution, designed independently.
- **Include the flows the people the purpose serves run every day** — iterative development, operation, teardown — not only the first launch.
- Where the design departs from the general structure of this kind of system, it needs a ground just as a plan does.
- Return only the design. Do not compare it with the plan or settle a verdict.

### 3. List the design as elements

List the design's elements, one for each unit of what the design adds or removes, numbered D1, D2, D3, … in order. For each, what it adds and what it removes (empty if nothing). Another reader will point at a plan's rows by these numbers, so the elements must not disagree with the design text.

## Done when

- You judged whether the question stands, and the reason is not empty.
- When it does not stand: the grounds are given, and everything real they name has an exact place at the commit the request is based on.
- When it stands: the design covers the everyday flows, not only the first launch, and every element is numbered in order and agrees with the design text.

## How to report

- Whether the question stands, and the reason — never empty.
- When it does not stand: the grounds, with an exact place for anything real you name.
- When it stands: the design and its elements.

## Example

Input: purpose "record which repository each deploy came from". Measured constraint: one deploy is built from exactly one repository.

Reply:
- The question does not stand.
- Reason: one deploy is one repository, so the repository itself identifies the deploy; there is nothing separate to record.
- Grounds: each deploy is built from the repository that holds its settings, `deploy/settings.yaml:4` (at the commit the request is based on).

## Works well with

- Judging blind from only what you were given.
- A look at the grounds for departing from the general structure of a system.
- Reviewing a plan against such a design before the fix is written.
