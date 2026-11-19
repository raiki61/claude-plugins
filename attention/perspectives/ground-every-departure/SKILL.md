---
name: ground-every-departure
description: Requires a ground for every departure of a change from the usual structure of its kind, accepting only a written rule of the target or an immovable outside fact, never the current state. Use when asked "is this departure justified" or why something is built differently from the norm. Not for drawing the usual structure itself.
---

# Require a ground for every departure from the general structure

**Core rule: compare the touched part with the general structure of the system that contains it, and give a ground for every place where the chosen form departs from it.**

The general structure of a kind of system is how practitioners commonly split such a system into parts, what flows between the parts and in which direction, where the source of truth of each value lives (the one place it is born), which way the dependencies point, and where the boundaries are drawn. It is not a particular solution or tool. Use the drawing of it you were given; otherwise, the way practitioners build such systems.

## Pitfalls (read first)

- **The current state is not a ground.** Its settings, code, layout, and habits, a precedent in the code (how the code solves the same problem today), and the fact that something does not exist yet.
- **A precedent counts only when it points the same way as the general structure.** When it points away, it is part of what the change may have to move, not a form to copy.
- **Aligning is not scope creep.** The work needed to bring the touched part in line with the general structure belongs to the same change: do not count it as widening the scope, do not leave it out as out of scope, and do not split it into another request. That the request did not foresee it is not a reason to leave it.

## Steps

### The only two grounds

1. **A rule the target (the repository the change is made in) decided in writing**: its constitution, rules, and design documents (the instruction files kept in that repository that write down its rules, such as `AGENTS.md`, and the documents those files point to as canonical), the policy for this piece of work, and a person's earlier decisions (answers a person gave when the work stopped to ask them, and recorded decisions). Such a rule wins over the general structure. Code comments and docstrings are not such rules.
2. **An outside fact that cannot be moved**: the specification of an outside tool or service, a law, or a contract.

### What else to write for a departure

Say what piles up if the same problem comes three more times and each time is solved by extending this form.

## Done when

- Every place where the chosen form departs from the general structure has one of the two grounds, or is counted as work the same change must do to align.
- No departure rests on the current state, or on a precedent that points away from the general structure.
- Every departure says what piles up if it is extended three more times.

## How to report

For each departure: where the chosen form departs from the general structure, its ground (which of the two, and the rule or fact itself), and what piles up if the same problem comes three more times. A departure with no ground is work for the same change, not a separate request.

## Example

Input: a change adds a second place that computes the shipping fee, next to the one that already exists, because "the checkout code already copies the tax logic the same way".

Reply:
- Departure: the shipping fee would have two sources of truth instead of one.
- Ground: none. "The checkout code already copies the tax logic" is a precedent that points away from the general structure, so it is not a ground.
- Piles up: three more such fixes give five copies of the fee rule that drift apart.
- So the change itself should compute the fee in one place.

## Works well with

- Drawing the general structure of the same kind of system as the touched one, which gives the picture this perspective compares against.
- Telling the recorded policy apart from the target's own text, which decides what counts as a rule decided in writing.
