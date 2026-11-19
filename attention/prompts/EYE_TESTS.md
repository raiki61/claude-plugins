---
vars:
  deleted: list   # stage 0 deletedTests: "<path>: <name>" per removed test, "<path> (whole file)", "<path> (not counted)"
---
Tests this PR removes (base has them, head does not; counted by the prep stage):
{{deleted|bullets}}
Pair each removed test with the test at the head that now checks the same behaviour. A removed test with no pair is a finding: name what it checked and that nothing checks it now. Also check every test double (mock, stub, fake) this PR adds or changes: does its shape (arguments, return values, errors, ordering) match the real thing it stands for? Cite the real thing's definition.
