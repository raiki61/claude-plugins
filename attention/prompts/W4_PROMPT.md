---
vars:
  prFiles: text
  question: text
  notAFinding: list # the NOT_A_FINDING items
  findingFields: text # the FINDING_FIELDS text
---
{{prFiles}}

Code-smell question: {{question}}

Answer it for this PR by reading the diff file and the code around it. verdict: "smell" when it is a problem here, "none" when it is not (say why in answer, and list in evidence the places you looked; quote may be empty and line 0), "unverified" when reading cannot decide it. For a smell, give each ground in evidence as path, line and the exact quote. Do not count lines by guessing: quote them. For a smell, also write in answer the concrete scenario: the change or input, then what goes wrong or what extra work it causes. Without a quoted line and a scenario it is not a smell. Rule these out first; if one applies, it is "none":
{{notAFinding|bullets}}

{{findingFields}}
