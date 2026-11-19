---
vars:
---
Hygiene of what this PR adds: for every resource it opens, starts, locks, creates or subscribes to, is the paired cleanup there on every path (errors included)? Does it use the platform's official mechanism where one exists, instead of a hand-made one? Does every wait, retry, loop and queue have a bound (a timeout, a count, a size)? Name the place and the missing pair or bound.
