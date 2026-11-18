---
vars:
  question: text
  verdict: text
  answer: text
  evidence: list   # "<location> :: <quote>"
---
Question: {{question}}
Answer ({{verdict}}): {{answer}}
Evidence:
{{evidence|bullets}}
