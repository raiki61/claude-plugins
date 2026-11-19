---
vars:
  claim: text   # one reason or assertion of the PR, as written (the purpose stage's claims, or a justification)
  at: text      # where it is: a path and line, or a comment URL
---
The PR says: "{{claim}}" (at {{at}}). Is this claim true? Check it in upstream primary sources or in code. The current state of base and the text this PR wrote are not reasons: a claim that rests only on them is circular. A claim of a count, or that something is there or not there, rests only on a value you measured again.
