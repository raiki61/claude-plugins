---
name: objection-rejudge
description: Reconsiders a binding review verdict when the fixing side objects, letting the objection through only on a new fact checked against the real code, never lowering a label, and admitting the judge's own mistakes. Use when someone pushes back on a verdict, or when told "they disagree with the judgment". Not for giving a first judgment.
---

# Re-judge an objection to a judgment

**Core rule: an objection passes only if it brings a new fact, and you check that fact yourself. Accepting without checking and rejecting without checking are both forbidden.**

Why: a written discipline said "if you object to a judgment, do not overturn it yourself; have a role in a different context re-judge it", but nothing closed that loop on the record. In practice the exchange happened in side conversations and left no trace, so a record could not tell it from a judgment that passed on the first try (measured once: five exchanges happened in one piece of work and only one was left; in two of them the code of the system running the judgment itself changed while the judgment was being made). Going through a re-judgment leaves the exchange itself on the record.

Here a unit is one item of the judgment: a bundle of findings with its label and its way to fix.

## Pitfalls (read first)

- **You did not write the first judgment in this conversation.** Read the first judgment and the materials it read (the files or records handed to you with the objection); do not rely on memory of a conversation. The repository is the target the judgment was about.
- **Read only.** Do not change a single character of the working tree.
- **"I am not convinced" does not open it.** Only a new fact does.
- **The authority to fix the judgment does not move.** The one who rewrites the judgment is you, not the fixing side. You may reject the objection.
- **Do not lower a label** (from block to suggest, for example).
- **How you answer does not change with how many times you have been asked.** Counting the exchanges is someone else's job.

## Steps

"What to do" applies every time; read "When the input is not enough" when what you need to check the objection is missing, and "If your own prescription was wrong, say so" when your check shows the first judgment erred.

### What to do

1. Check each fact the objection gives **against the real thing**: the lines concerned, a reproduction of the measurement, a search. If you cannot run anything, reproduce by reading the records (logs, materials) and the code, and see whether the value comes out the same.
2. For a fact you cannot check — including one that cannot be checked without running something — say so: start with "Cannot check:" and write what you could not read and what you could not compare. That is a check result, not a refusal to check. **Do not use an unchecked fact as a ground for accepting.**
3. Decide by the facts you could check only: accept, reject, or accept in part.
4. Rewrite only the units that need to change, but hand back the whole set of units, including the ones you did not change, so nothing disappears by omission.
5. Give, in one line, why you judged so.

If a policy applies, judge the objection against it too, and do not let through on your own anything that cannot hold without changing it.

### When the input is not enough

If what you need to check the objection (its sentence, the lines it points at, a file) is in neither the materials nor the repository, there is no ground to change the judgment: reject, keep the units as they were, and say "Not enough:" with what is missing and what you could not check. This is a reply that says it could not check, not a rejection without checking. If not even one fact of the objection could be checked, it is the same.

### If your own prescription was wrong, say so

It has happened: a zero prescription the judge wrote (the smallest fix: withdraw, or settle it with one existing mechanism) lacked one word, and the fixing side's attempt to apply it failed. A judgment that admits its mistake works better in the next judgment than one that does not.

## Done when

- Every fact the objection gives has been checked against the real thing, or marked "Cannot check:" with what could not be read or compared.
- The verdict rests only on checked facts.
- No label is lowered.
- The whole set of units is in hand, changed and unchanged.

## How to report

- The verdict: accept, reject, or accept in part.
- For each fact of the objection, what you checked and what you saw, or "Cannot check:" with what you could not read and compare; "Not enough:" first when the input was missing.
- The whole set of units, with only those that needed to change rewritten.
- One line on why you judged so.

## Example

Input: the fixing side objects that a block unit is wrong because "this function is never called with an empty list", and cites a search that found two callers.

Reply:
- Verdict: reject.
- Checked: the cited search finds the two callers, but a third caller on another path passes the result of a filter that can be empty (its path and line).
- Units: all returned; none changed; the block stays a block.
- Why: the new fact claimed does not hold in the code.

## Works well with

- A perspective that first sorts a fix request and its review findings into root-cause units, each with a label and a fix.
