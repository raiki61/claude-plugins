---
name: prior-decisions-check
description: Searches the decision records of the area a change or request touches (ADRs, ledgers of deliberate deferrals, rejected issues and pull requests) and names every request line that would overturn a settled point. Use when the area to change has a history, or when asked "did we reject this before". Not for checking whether a change's cited grounds existed before it.
---

# Check a change or a request against earlier decisions

**Core rule: list what was already settled in the area, each with where it is written, and name every request line that would overturn a settled point.**

## Pitfalls (read first)

- **Comments, docstrings, and test descriptions are not decision records.** If one of them names an issue or a decision record, read what it names and list that, pointing to where it is written.
- **A settled point without a place cannot be named.** Every settled point carries where it is written, so that later readers can cite it.
- **When there is no diff yet, search where the request points.** When the request aims at existing code, an empty diff is normal, and what is about to change is the place the request names.
- **Read the area the change touches first.** This is advice on order, not a boundary.
- **Judge a conflict by what a line asks, not by where it points.** Two lines that point to the same place may ask for opposite things.
- **If you could not search the records, do not write "no settled points".** Say that the search could not be done, why, and what you did read. An unchecked area is not a clean one.
- **Say what you searched and what you did not.**
- **Read only.**

## Steps

1. Search the decision records of the area the change touches — decision records such as ADRs, the ledger of deliberate deferrals, rejected issues and pull requests, closed issues — or, when there is no diff yet, of the places the request points to.
2. List each settled point with its topic, decision, reason, condition for revisiting, and where it is written.
3. For each request line, compare what it asks with the settled points, and note every line that would overturn one.

## Done when

- Every settled point carries where it is written.
- Every request line that would overturn a settled point is named. Whether it overturns one was judged by what the line asks, not by where it points.
- The range you searched and the range you did not are written down; if you could not search, that is said instead of "no settled points".

## How to report

- **Settled points**: one per point — topic, decision, reason, condition for revisiting, and where it is written.
- **Conflicts**: one per pair — the settled decision, the place the request line points to (the place it names — a file, an area, or the like — copied exactly), and how the line goes against the decision. Empty if none.
- **Searched**: the range you looked at and the range you did not.

When you name a place in a file, give the line number in the current file, not a line in the diff: lines of a diff are not lines of the file, and a person cannot open that place. Open the file and confirm the line before writing it; if you cannot, give the path with a function name or similar instead of a line number.

## Example

Input: a request line "remove the limit on upload retries". A decision record in the area says: retry uploads at most three times, because the storage provider blocks clients that retry more; revisit if the provider changes.

Reply:
- Settled points: upload retries — at most three — the provider blocks clients that retry more — revisit if the provider changes — the decision record on upload retries.
- Conflicts: the request line "remove the limit on upload retries" asks for no limit, which overturns the three-retry decision.
- Searched: decision records and closed issues about uploads. Not searched: rejected pull requests.

## Works well with

- A perspective that sets the stance of a read-only investigator who goes to primary sources (it rewrites no files, opens primary sources such as the original records and official documents itself, and when it finds nothing, says where it looked). It fits the reading of decision records in step 1.
