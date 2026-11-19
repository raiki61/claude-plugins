---
name: reinvention-check
description: Checks finished code against outside standards and the installed code of declared dependencies, to find hand-built versions of what an established solution already does. Use when a change builds its own retry, cache, escaping, or similar utility, or when asked "doesn't a library already do this". Not for consistency with the repository's own code, nor for vetting a request before building.
---

# Check whether a change reinvents an established solution, down to the ranking

**Core rule: start from "I cannot be the first to solve this problem". Look outside the repository — official documents, the issues and changes and source of the relevant open-source projects — and inside the installed files of its declared dependencies. Do not judge a change the same as the standard because its features match: find the order in which the primary source ranks the options, say which option the change is on, and if it is not the top one, say why the higher ones cannot be taken.**

Repository-wide search and diff-only review aim at nearby things but use different sources; this perspective alone goes outside.

## Pitfalls (read first)

- **Matching features is not the same shape.** A degraded variant of an established solution appears exactly in the form whose features match. (Measured once: three reviews in a row returned "the same as the standard" for a change that avoided the shell and used an allow list — but the standard (the OWASP cheat sheet on OS command injection defense) ranks "separate data and command by structure" above "validate the string", and the change was on the lower option.)
- **Look with your own eyes first.** Do not start from local review findings: seeing them pulls the choice of problem classes toward them.
- **When no purpose is given, do not invent one.** Draw the problem classes from the change and its dependencies.
- **No source URL, no assertion.** Blogs and Q&A sites stay hypotheses; if you cannot confirm, say "not confirmed". Take every primary source you need to confirm a point; drop only redundant sources and duplicate secondary ones.
- **Only declared dependencies count as "already at hand".** A package that is present only because another dependency brought it vanishes the day that parent switches; leaning on it is a design decision about adopting it, not an unused dependency. (Measured once: "the validation layer is home-made" was raised three reviews in a row because an undeclared validation library sat in the installed dependency folder; each time it fell into the separate decision "promote it to a dependency", and it was carried over unresolved.)
- **"Already at hand but unused" is not only what is imported.** Start from the dependencies the change imports (a set you can derive quickly), but do not stop there: what the repository declares as a dependency — not only packages, but declared plugins and tools — is where to look, even if nothing imports it. (Measured once: a role that the project itself declared as a dependency fell outside the imported set, and "no reinvention" came back for three reviews.)
- **"No established solution exists, so building it is right" is a valid conclusion** in in-house domains and areas with no de-facto standard yet. Doubting is not forcing everything into something existing.
- **"Did not look" is not "found nothing".** Say what range you looked at and what range you did not; if you stopped because of volume or time, say where. The diff is where to start, not where to stop: read dependencies, the neighbourhood, and callers as far as you need.
- **Read only.** Do not create, edit, or delete files. If a command is refused or cannot reach what it needs, report that check as not measured, with the command and how it was refused; do not respell the command to get it through.
- **Do not put the target's names into outside queries.**

## Steps

Do "What to check" for the change as a whole; then do "Ranking" for each general problem it solves.

### What to check

- If the target repository has its own review guide, read it too.
- **Extract the problem class**: state in one sentence the problem the diff solves. If it belongs to a general class (initialisation order, authentication and authorisation, retry, caching, concurrency control, serialisation, and so on), doubt whether an established solution exists.
- **Confirm in primary sources**: search the web for the established solution and its known pitfalls, and confirm in official documents, the project's issues and changes, and source.
- **Unused dependencies at hand**: read the actual installed files of the declared dependencies, and check whether something equivalent to what was hand-built is there, or whether it is a matter of **a setting or option of a dependency already in use**. Web search sees only "is there a solution in the world"; **"already installed but not used" slips past it**. Two forms of the mistake: (1) the same function is hand-written (and the hand-written side usually lacks what the original carries); (2) a problem one upstream setting avoids is crushed by adding conversion downstream.
- **Granularity**: not only how an API is used, but home-made utilities and whole pipelines and foundations. The highest leverage is finding "the whole mechanism was home-made but an established solution existed".
- **Use comment density as a clue**: a place that cannot be read without thick explanation is also a sign that the home-made part is thick. On an established solution, readers already know it and no explanation is needed. Doubt first the files and functions with a strikingly high comment ratio: should this have been built at all? (Do not go straight to trimming comments: what should go may be the home-made code that makes the explanation necessary.)
- **Re-check accepted weaknesses**: weaknesses written as "known and accepted" in the change's description, the README, or notes of what remains are not exempt. Being aware does not mean no fix exists (manual operation that a standard mechanism, or a field a standard already defines, could replace is typical).

### Ranking, for each general problem the change solves

1. State the problem as a general problem class.
2. Find in primary sources the established solutions and their known pitfalls.
3. **Ranking**: write the options in the order the source gives them, from the top; quote the source.
4. Say which option the change is on, spelled as in that list.
5. If it is not the top one, say why each higher one cannot be taken.
6. For a problem with no ranking, the list may hold a single option. If there is no general problem that can be ranked, say so and say why.

## Done when

- Each general problem has its ranked options with the quoted source, the option the change is on, and why each higher one cannot be taken — or there is a stated reason no problem could be ranked.
- Each finding has: **the mechanism** (one sentence on the causal chain in the code); **a measurement** (run what can be run; if you cannot, say "not measured" and give it as a hypothesis); **a self-refutation** done first (if you cite a rule, check that its conditions apply, read the actual code around it, and submit only what you could not kill); and **a false-positive estimate** (one line on when the finding would be wrong).
- The range you looked at and the range you did not are both written.

## How to report

For each general problem: the problem, the ranked options with the quoted source, the option the change is on, and why the higher ones cannot be taken. Then the findings, each with the four items above, and the range you looked at and did not. Point to a place by its path and a line number in the current file, confirmed by reading it — not a line inside a patch; if you cannot read the file, give the path and a function name instead.

## Example

Input: a change wraps calls to an outside service in its own loop that retries with a fixed sleep. The repository already declares a client library for that service.

Reply: Problem: retrying outside calls. Ranked (the client's official documentation, quoted): 1 the client's built-in retry setting with backoff; 2 a hand-written loop. The change is on: 2. Why not 1: none found. Finding (not measured, hypothesis): a setting of a declared dependency covers this. Looked at: the client's installed files. Not looked at: other callers.

## Works well with

- A set of rules that keeps the reviewed repository's own names and text out of queries sent to outside services (web searches, fetched URLs).
