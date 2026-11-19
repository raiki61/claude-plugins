---
name: remeasure-premises
description: Measures again in the current working tree every number, count, existence claim, and "X turns red" claim a request makes before diagnosing or planning, attaching the command and output or marking it a hypothesis. Use when a request makes numeric or existence claims about the code, or when asked "are the request's numbers still true". Not for fixing the purpose of the work.
---

# Measure the request's premises again before anything is built on them

**Core rule: a claim becomes a premise only after it is a value measured in this working tree, or a fact that names a file, shown with the command that was run and its output. Anything else is a hypothesis.**

Why: whoever comes later reads these premises as given. A wrong fact handed on here sends every judgment and fix built on it off course, and a wrong premise still passes their judgment.

## Pitfalls (read first)

- **Do not trust the requester's measurement as written.** It may come from another version, another working tree, or a path that is gone. Measure it again here; if it does not match, write the value you measured and the difference from the request's value.
  - A real case: a request claimed "the body is up to about 4MB", but the 4MB was measured on a file path that the change under review had itself deleted. The real size was 5,411 bytes, and five passes of work were built on that wrong premise.
- **Only "measured" is trusted without a recheck.** So a wrong "measured" is passed on unquestioned even to those who later question everything else from zero, and their judgments are built on it.
  - A real case: "the repository has no CI definition" was recorded as measured, but a CI workflow file existed. Even when other parts of the same piece of work were written on that premise, it was not corrected.
- **Do not hand on memory, an earlier measurement, or a general statement as a premise.**
- **"Does not exist" needs where you looked.** Paste the place and the command; an empty listing or an empty search is also output.
- **Do not change a single character of the working tree, or move its history.** What you measured would otherwise mix into the diff of the later fix. Write any output outside the working tree; if you create something by mistake, remove it, or restore a tracked file you rewrote, before you finish.

## Steps

1. From each request line, pick up every claim about numbers, sizes, counts, exists / does not exist, "X can arrive" (some input or value can reach a given place), and "X turns red" (a given test or check fails) — in what it says, the mechanism it gives, and the condition under which it would be a false alarm.
2. For every line that carries a measured value, write at least one constraint, and quote that line's location in it exactly as written.
3. Measure each claim in this working tree (counting, sizes, listings, the history, running tests, and so on).
4. A fact that names a file also needs a command that shows it (a listing, a search with line numbers). Run it and attach its output.
5. Mark each constraint:
   - **measured**: you can show the command you ran and its output;
   - **hypothesis**: you cannot — for example production input or things outside the target. Never copy the requester's value as measured.
6. When what you measured contradicts what a request line claims or assumes, note which line it contradicts.
7. If the request has no claim to measure, the list may be empty.

A lookup that could not be run because it needs the target's names is handed on as a hypothesis.

## Done when

- Every claim of the kinds in step 1 is a constraint, and every request line with a measured value has at least one constraint quoting its location.
- Every constraint says how it was measured, and every "measured" constraint has its command and output attached; everything else is marked hypothesis.
- Every "does not exist" shows where you looked.
- The working tree and its history are as they were when you started.

## How to report

A list of constraints. For each:

- the constraint (the measured value, or the fact that names a file; when it differs from the request's value, both);
- how you measured it;
- the mark, measured or hypothesis;
- for measured, the command and its output (only the needed lines if it is long; start command lines with `$ `);
- for a hypothesis, the location and why it cannot be measured; for a lookup not run, what you wanted to confirm and that it was not run;
- for a constraint that contradicts a request line, that line's location, copied exactly.

## Example

Input: A request line at `notes/request.md:3` says "the cache folder holds about 200 files, so listing it is slow."

Reply:
- Constraint: the cache folder holds 12 files, not about 200 (`notes/request.md:3`). Measured by counting the entries of the folder. Mark: measured.
  `$ <list the cache folder and count the lines>` → `12`
- Contradicts: `notes/request.md:3`.
- Constraint: "listing it is slow" in production cannot be measured here (`notes/request.md:3`; production input is outside the target). Mark: hypothesis.

## Works well with

- keeping the target repository's names and paths out of queries sent to outside services such as web search (so that possibly private names do not stay in outside records).
