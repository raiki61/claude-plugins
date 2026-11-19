---
name: test-double-fidelity
description: Checks whether the mocks, stubs, and fakes at a seam a change touches have the same shape as the real thing, using one value actually taken from it. Use when tests of an outside seam rely on doubles, or when asked "does this mock match the real API". Not for running the real path end to end.
---

# Check that test doubles at a seam have the real thing's shape

**Core rule: judge a double not by how faithfully it reproduces the real thing, but by whether an error in the implementation can be observed through it — and check its shape against one value taken from the real thing.**

A double whose input shape differs from the real thing cannot observe the error: the test turns green on a shape that only the double accepts.

## Pitfalls (read first)

- **Applies when the change touches a seam with the outside**: another process, another service, a browser, an outside API, a protocol.
- **Compare with a real value.** Take one value from the real thing and hold the double's shape against it.
- **Do not break the real working tree.** Make any copy you need for running in a fresh temporary directory outside it.

## Steps

1. Find the seams with the outside that the change touches, and the test doubles (mocks, stubs, fakes) that stand in for them.
2. For each double, take one value from the real thing.
3. Hold the double's shape against that value, and note every place where they differ.

## Done when

- Every double at a touched seam was held against a value taken from the real thing.
- Every mismatch has its place and what differs; if there is none, what you compared with what is written down.
- If you could not check, that is said with the reason, instead of reporting no mismatches.

## How to report

One row per mismatch: where (the path and line in the current file), and what differs — with the mechanism, whether it was measured, and when it would be a false positive, when useful. If there is none, say what you compared with what. If you could not check, say so and why.

The line is the line number in the current file, not a line in the diff: lines of a diff are not lines of the file, and a person cannot open that place. Open the file and confirm the line before writing it; if you cannot, give the path with a function name or similar instead of a line number.

## Example

Input: a change calls a payment service. Its test stub returns `{"amount": 100}`. One response taken from the service's test environment is `{"amount": "100.00", "currency": "EUR"}`.

Reply: Mismatch — where: the payment stub file, line 14. The stub returns the amount as a number; the real service returns a string with two decimals, plus a currency. Mechanism: the change's parser accepts numbers only, so the test passes on a shape the real service never sends. Measured: yes, from one real response.

## Works well with

- A set of rules that keeps the reviewed repository's own names and text out of queries sent to outside services (web searches, fetched URLs).
