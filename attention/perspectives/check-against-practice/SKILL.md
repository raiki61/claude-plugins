---
name: check-against-practice
description: Restates each line of a change request as a general kind of work and judges whether the means the request proposes matches how practitioners solve it. Use when a request names a specific mechanism and nothing is built yet, or when asked "how does the world solve this". Not for reviewing finished code for hand-built copies of an established library.
---

# Check a request against how practitioners solve it

**Core rule: do not ask about the parts of the mechanism the request names, or about the output format of a tool. Ask how practitioners do this kind of work.**

A request usually arrives already shaped as a means ("add X so that Y is judged"). Taken as given, the means hides the question of whether the work should be done that way at all. This perspective steps up from the named mechanism to the kind of work, finds the established practice for that kind of work, and only then compares the request's means with it.

## Pitfalls (read first)

- **The means is a proposal to doubt, not a given.** Whether it is good is decided against the practice that is found, never before.
- **Restate before you look at the target.** Reading the target's code first pulls the restatement down into its mechanism. Do the restatement from the request text alone (or have an eye that cannot see the target do it).
- **Never paraphrase an excerpt.** An excerpt is copied word for word from a page you actually opened. A paraphrase or a summary presented as a quote is not evidence.
- **Never cite a page you did not open.** A URL that only appeared in a search result list is not a source.
- **Never put the target's names into an outside query.** A query sent to a service that does not hold the target stays in its records.

## Steps

### 1. Restate each request line as a problem class

For every line of the request:

- **Problem**: one sentence that states the line as a problem class, in the words of the work practitioners do. Step up one level to the kind of work: even if the request says "add X so that Y is judged", the class is neither how to build X nor how to read Y. Shape of an example: "in test-first development, how to make a test that calls a not-yet-existing function fail for a target that must be compiled".
- **Activity**: a short name for the kind of work.
- **Proposed means**: the means the request proposes, set apart from the problem, in words of the means. Empty if the request proposes none. Keep it out of the problem and out of the queries.
- **Queries**: one or a few search queries that ask how practitioners solve this class: practice, convention, standards.
- If one line spans two kinds of work, restate it as the one kind above both.
- Remove the target's names (paths, files, functions, fields, environment variables, component names, ids of jobs and builds) from the problem, the activity, the proposed means, and the queries.

### 2. Find the practice

- Search with the queries; you may add queries, without the target's names.
- Prefer primary sources (standards, official documentation, original texts) over secondary ones.
- Check that a source fits the situation of this request, not just its keywords.
- Bring back excerpts copied word for word from the pages you opened, long enough to carry the point.
- State the practice in one to three sentences, from the excerpts, without the target's names.
- When you find no source for a class, state the practice from your own knowledge and mark it plainly as not confirmed by a source.

### 3. Judge how the practice applies

For each class:

- **Applies**: how the practice applies to this request.
- **Does not apply**: where it does not. If it does not apply to this request at all, say so instead of forcing it.
- **Verdict on the means**: the same as the practice, different from it, or no means proposed.
- **When it differs**, name the difference and recommend the practice, in this form: "The request does X; the practice is Y. Choose Y unless …". The "unless" names what would have to be true for the request's means to win.

## Done when

- Every request line is restated as a problem class, with the proposed means set apart, and none of the four parts holds a name of the target.
- Every class has a practice stated from excerpts of pages you opened, or is marked plainly as not confirmed by a source.
- Every class has a verdict on the means, and every difference carries the "Choose Y unless …" recommendation.

## How to report

For each request line: the problem, the activity, the proposed means (or empty), and the queries. For each class: the practice in one to three sentences, with the sources and the excerpts copied from them (or the mark that no source confirmed it); where it applies and where it does not; the verdict on the means; and, when it differs, the recommendation in the form above.

## Example

Input: a request line, "add a retry counter to the upload so that flaky uploads are judged".

Reply:
- Problem: how to make a transfer over an unreliable network succeed without repeating its effect. Activity: retrying idempotent requests. Proposed means: a retry counter. Queries: "retry with exponential backoff idempotent request practice".
- Practice (from an opened page, excerpt copied): retry only requests that are idempotent, with backoff and a cap.
- Verdict: different. "The request counts retries; the practice is backoff with a cap on idempotent requests. Choose the practice unless the upload cannot be made idempotent."

## Works well with

- A perspective that keeps the names and text of the target out of queries sent to outside services (web search, web fetch, and the like) and goes to primary sources first.
