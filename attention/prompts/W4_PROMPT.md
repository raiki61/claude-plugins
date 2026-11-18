---
vars:
  prFiles: text
  question: text
---
{{prFiles}}

Code-smell question: {{question}}

Answer it for this PR by reading the diff file and the code around it. verdict: "smell" when it is a problem here, "none" when it is not (say why in answer, and list in evidence the places you looked; quote may be empty and line 0), "unverified" when reading cannot decide it. For a smell, give each ground in evidence as path, line and the exact quote. Do not count lines by guessing: quote them.
