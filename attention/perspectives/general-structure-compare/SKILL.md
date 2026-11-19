---
name: general-structure-compare
description: Draws the system around a change as it actually is, has an eye that sees only a name-free sentence draw the usual structure of that kind of system, and lists the differences. Use when a change touches how a system is split or where values are born, or when asked "how is this kind of system usually built". Not for deciding whether an already-found departure is justified.
---

# Compare the touched system with the general structure of its kind

**Core rule: draw what the repository is, not what it should be; draw the general structure from the kind of system alone, without seeing the repository; then compare structure, not wording.**

The general structure of a kind of system is how practitioners commonly split it into parts, what flows between the parts and in which direction, where the source of truth of each value lives (the one place it is born), which way the dependencies point, and where the boundaries are drawn (what each side may know of the other).

## Pitfalls (read first)

- **Keep the three eyes apart.** The one who draws the repository does not judge the fix or propose a way to make it. The one who draws the general structure sees only the sentence about the kind of system. The comparison is fair only if neither drawing leans toward the other.
- **The kind sentence must not leak the repository.** A sentence that already says how this repository does it spoils the comparison.
- **Draw the structure, not a solution or a product.** Name parts by their role; name a tool or a service only as an example of a part.
- **A difference in wording is not a difference.** Compare how the parts are cut, the direction of the flows, where the source of truth lives, the direction of the dependencies, and where the boundaries are.

## Steps

The steps belong to three eyes: the first two to the eye that reads the repository, the third to the eye that sees only the sentence, and the fourth to the eye that compares.

### 1. Draw the system as it is

Only read; do not change a single character of the working tree. For each part of the change (one fix, or the files it touches), read the files it names and what is around them, and draw the system that contains the touched part:

- its parts, what flows between them and in which direction, where the source of truth of each value the touched part handles lives, which way the dependencies point, and where the boundaries are;
- follow the flows beyond those files: where a value the touched part uses is born, who passes it on, and who reads it;
- name each part by its role in the system (for example "the side that provisions the resources" or "the side that deploys the application"), and add in parentheses the paths where it lives, so that the comparing eye can find it.

### 2. Say what kind of system it is

One sentence that says what kind of system this is and what the touched part has to keep consistent in it, written for a reader who knows nothing of this repository. Leave out the repository's names, paths, file names, identifiers, product names, and the words of the change's own summary. Ordinary words such as "config" or "server" are fine; a word that looks like an identifier (a hyphen, an underscore, a digit, or a capital letter inside a word) is not.

### 3. Draw the general structure (an eye that sees only the sentence)

From the sentence alone, draw the general structure of that kind of system as practitioners commonly build it: the parts, the flows and their direction, the source of truth of each value the sentence names, the direction of the dependencies, and the boundaries.

- Where practitioners split into more than one common structure, draw the one most commonly recommended and name the other.
- Say why such systems are commonly built that way: what goes wrong when the source of truth, a flow, or a boundary is put elsewhere.
- Do not reconstruct by guessing what you were not given. Before drawing, doubt that the question holds; if it does not, say so with the grounds instead of drawing.

### 4. Compare

Put the drawing of the repository and the general structure side by side and find the differences. For each difference in the part the change touches (one the change keeps, adds, or deepens), decide whether to bring it in line with the general structure or to depart from it, and require a ground for every departure.

- A change that keeps, adds, or deepens such a difference with no ground dirties the structure. Recommend the form in line with the general structure, together with the changes outside the change's own files that it needs.

## Done when

- The drawing of the repository is of what is, with each part named by its role and its paths.
- The kind sentence carries no name, path, identifier, or word of the change's summary.
- The general structure was drawn from the sentence alone, with why such systems are built that way.
- Every difference in the touched part is decided: in line, or a departure with its ground.

## How to report

- **Drawing the repository**: the parts by role with their paths, the flows and their direction, the source of truth of each value, the dependency direction, and the boundaries; then the kind sentence.
- **Drawing the general structure**: the structure, why it is commonly built that way, and any other common structure by name; or, when the question does not hold, that and its grounds.
- **Comparing**: each difference, how you decided it, and the parts of both drawings you rest on; for a difference kept with no ground, the recommended form and the changes outside the change's files that it needs.

## Example

Input: A change adds a second place that computes the price with tax, beside the one that already does. The kind sentence: "a shop system in which the displayed price and the charged price must agree."

Reply:
- General structure: one pricing part is the source of truth of the price; display and payment both read from it. Why: when each computes its own, the shown and the charged price drift apart.
- Difference: after the change, the price is computed in two places (the display side and the payment side, each with its paths); the general structure has one. The change adds this difference with no ground, so it dirties the structure. Recommended: have the payment side read the price from the part that already computes it.

## Works well with

- deciding what counts as a ground for departing from the general structure;
- judging whether a change makes more places know a design concept.
