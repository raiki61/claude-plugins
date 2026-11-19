---
name: purpose-apart-from-means
description: Writes the original purpose of a piece of work as one sentence, apart from the means it proposes, fixed before the work starts and taken from the best available source. Use when work on a request begins and its goal must be pinned, or when asked "what is this request really for". Not for restating request lines as general kinds of problems.
---

# Fix the purpose before the work, apart from the means

**Core rule: the purpose sentence says only what the request wants to reach, and why — never the means it proposes — and it is fixed before the first fix starts and not changed afterwards.**

Why: if means mix into the purpose sentence, a design made from the purpose alone falls into the frame of the same means, and the proposal is taken as given before it is compared with practice. If the purpose could be rewritten later, a path would open to narrow it to fit the implementation (this is pre-registration).

## Pitfalls (read first)

- **The request's means is a proposal to doubt against practice, not the purpose.** List each means apart, one sentence each; do not repeat the purpose there.
- **The purpose sentence is read later on its own, without the request.** It alone must say what the work should reach and when the work is done.
- **Read only.** Do not change a single character of the working tree.
- **Do not make up a plausible purpose.** When no source can be found, say so.
- **Use only measured numbers.** If you write numbers, sizes, or counts in the purpose, use only values that were measured, never a hypothesis.
- **The judgments of earlier attempts at the work are not a source.**

## Steps

Read sections 1 and 2 when you write the purpose; read section 3 when you are the other eye checking a purpose its writer had to summarize.

### 1. Find the source, in this order

1. The PR description.
2. A plan document or a task description (preferred to a summary, because it was written apart from the implementation). A request that describes a plan or a task (what to build or fix) counts as this. You may look for plan, design, or task documents inside the target repository yourself; do not look outside it.
3. Only when there is neither, summarize the purpose yourself (the last resort). A request that only lists findings, from which you summarize the purpose, counts as this. Do not shrink the purpose to the scope already implemented, and do not silently drop requirements the implementation cannot meet; someone else will check whether you narrowed it.
4. When no source can be found, write "unknown" followed by the sources you looked for and did not find (PR description, request, plan documents). A design made from the purpose cannot then be checked.

### 2. Write it

- **Purpose**: one sentence, never empty, with the means removed.
- **Source files**: the files in the repository you used as sources, as exact paths from the repository root (normal form, the repository's letter case, no `./`, trailing `/`, `.` or `..`, no path through a symlink, not ignored by version control). They are fixed together with the purpose and later compared character for character with the names of the files a change touched; a source left out or written in another form never matches, so a later change to it is not noticed. Do not list things outside the repository.
- **Means**: the means the request proposes, copied from its text, one sentence each (leave it out if there are none).
- **Known weaknesses**: the weaknesses that the PR description, a README, notes on remaining work, and the like state as "known and accepted", each with its source. Write them even when the purpose is unknown. They are for whoever compares the work with outside standards.

### 3. Check a self-written purpose for narrowing (another eye)

When the purpose had to be summarized by its writer (there was neither a PR description nor a plan), a separate eye, given only the purpose text and the repository at the fixed version, checks: against the actual scope of the change, the issue, and the plan, has the purpose shrunk to fit what is already implemented, and has a requirement the implementation cannot meet been silently dropped?

- **Every finding brings evidence that can be looked up in the repository**: a one-line string that exists in the files now (not from memory or an earlier answer), and the number of lines it appears on.
- **You may point out an absence**: processing that should exist but is nowhere. The absence itself is often the strongest evidence of narrowing. Cite a string that exists around the place where it is missing (for example the definition line of the function where it should be), and say that it is missing there.
- **When input is insufficient** (the purpose text is empty, the files cannot be read), give no verdict: start the reason with "missing:" and say what is missing.
- Read the fixed version, not a working tree that may be changing.

## Done when

- **Writing**: the purpose sentence is not empty, holds no means, uses only measured numbers, and says on its own what the work should reach; or it is "unknown" with the sources looked for. The source files are exact paths inside the repository.
- **Checking**: there is one verdict with evidence that can be looked up, a "narrowed" verdict has at least one finding, or the reason starts with "missing:".

## How to report

- **Writing**: the purpose sentence; the source it came from (PR description, plan or task, your own summary, or unknown); the source files; the means, one sentence each; and the known weaknesses, each with its source.
- **Checking**: the verdict — no problem, or narrowed — and for each finding, what it says, the one-line string it cites, and the number of lines that string appears on; or, when input is insufficient, a reason starting with "missing:" and no verdict.

## Example

Input: There is no PR description and no plan. The request lists two findings: the export drops rows with empty names; the export file has no header row.

Reply:
- Purpose: the export writes every row of the table, with a header row, so that the file can be read back without losing data. Source: your own summary (the request only lists findings).
- Means: none proposed.
- Known weaknesses: none stated.

## Works well with

- keeping the target repository's names and paths out of queries sent to outside services such as web search;
- comparing a request's means with how practitioners solve the same kind of work.
