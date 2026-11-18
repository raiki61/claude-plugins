---
vars:
  question: text
  answer: text
  files: list
  urls: list
  premises: list
  evidence: list   # "<location> :: <quote>"
---
Question: {{question}}
Answer: {{answer}}
Checked: files {{files|join:", "|or:"-"}}; urls {{urls|join:", "|or:"-"}}
Assumed without checking: {{premises|join:"; "|or:"nothing"}}
Evidence:
{{evidence|bullets}}
