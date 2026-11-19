---
name: change-minimality
description: Judges whether a finished change is the smallest one that does the job, measuring size by how many places know each concept rather than by lines. Use when a written change awaits acceptance, or when asked "is this change bigger than it needs to be". Not for choosing a prescription before any fix is written.
---

# Judge whether a change is minimal

**Core rule: a change is minimal when, after it, no concept is known by more places than before. Count places, not lines.**

A place that knows a concept is a place that writes its word, field name, value, or condition. A change that grew in lines to move a concept to its home (the one place that holds it) is minimal; a change that got by with a few lines but let one more place know the same concept is not.

To find a concept's home: if the repository keeps a map of where concepts live (a document saying which file holds which concept), read it first; when there are several maps, follow the map of the folder that holds the changed file. If there is no map, find the homes from the repository's own structure.

## Pitfalls (read first)

- **You did not write the change.** Do not take over its author's reasoning; try to refute, not to confirm.
- **Key only on information.** Ask whether something carries information found nowhere else (facts, the grounds of a derivation, a why). Do not use the writer's intent in the judgment.
- **Simplify under constraints.** Remove only what does not lose verified value: behaviour, tests, the reproducibility of a derivation.
- **The order is fixed**: first "is the needed content there (can a cold reader reproduce it from the text alone)", then "given that it is there, is it minimal".
- **Repetition is not protected automatically.** Protect a repeated piece only when you can say in one sentence that the reader's path needs it.
- **A missing input is not a pass.** If the change, the list of questions you were given, or the rules you judge against cannot be read and you cannot judge without guessing, say what is missing instead of guessing.
- **An absent side input does not stop the judgment.** If the list of comments proposed for removal could not be obtained, or no list of questions was given at all, say so and judge with the rest.

## Steps

### Start from the zero prescription

Measure every prescription the change took against the smallest one: the zero prescription — withdrawing the change, or using one existing mechanism. A larger prescription must carry the reason the smaller one fell. A mechanism added without that listing is not justified. A deviation from the plan that was accepted beforehand is judged by the content of its reason, not by the count of deviations.

### What to look for

1. **Concept homes.** If the places that know a concept whose home you can name have grown, that is a finding: name the concept, the home, and each grown place. If only places that know a concept with no home have grown, record it as an increment that may be justified, not as a finding.
2. **Symptom patches.** Small fixes piling up where one root fix would do.
3. **Derivable duplicates.** Content that can be derived from elsewhere, and places that could carry the same purpose with less text.
4. **Unused additions.** Public names or functions the change added that nothing uses. Check the warnings of the last test run if they cover this; otherwise search for uses by name, and say that you did.
5. **Unjustified increments.** For each chunk added without offsetting deletions, say where it is and whether it carries information found nowhere else. One that cannot be justified is a target for consolidation or relocation.
6. **Comments.** A comment proposed for removal, whose same content you can find at the named place, is removed. A kept comment whose carried fact could not be stated is a removal candidate. Where the explanation drifted from the purpose, fix it by structure or names, not by notes.

### Audit the questions handed to a person

A question passed to a person can be an escape route for work that could have been fixed. Count it as a finding when:

- it was cut out as a separate, pre-existing problem, but the work it came from lies inside the purpose set for the change (work inside the purpose cut out as if it were outside);
- it is a design fork whose options go to a person without listing or rejecting a zero prescription;
- it is a known break the fix let through and handed to a person, but judged by its content it could have been fixed with a zero prescription. Do not take "it is not in the list of questions" as a reason to excuse it.

Give a verdict for each question, one line each.

### Verdict

- **Pass** only when nothing above was found.
- **Needs a fix** when everything found closes with a zero prescription.
- **Needs a redesign** only when you can name a design point that does not close with a zero prescription; name each such point.
- Whether a finding needs a fix or a redesign is decided by whether such a point is named, not by how serious it sounds.

## Done when

- Every prescription the change took was measured against the zero prescription.
- Each of the six points in "What to look for" was checked, and every finding names its place.
- Every question handed to a person has its one-line verdict.
- The verdict follows the rules in "Verdict", or what is missing is named.

## How to report

- The verdict: pass, needs a fix, needs a redesign, or what is missing when you could not judge.
- Each finding with its place: for a concept home, the concept, the home, and each grown place; for an unused addition, its name and place, and whether you searched by name.
- One line per added chunk without offsetting deletions: where it is, and whether it carries information found nowhere else.
- One line per question handed to a person, with its verdict.
- For a redesign, each design point that does not close with a zero prescription, one line each.

## Example

Input: a change adds a retry limit of 3 as a new constant in the client module, while the settings file, which the repository's concept map names as the home of limits, already holds a retry limit.

Reply:
- Verdict: needs a fix.
- Concept home: the retry limit. Home: the settings file. Grown place: the new constant in the client module. A zero prescription closes it: read the limit from the settings file.

## Works well with

- A perspective that sorts the comments a change added into removals and keeps, each with its reason.
