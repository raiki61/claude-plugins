---
vars:
  question: text   # the smell question
  answer: text     # W4's answer
  where: list      # the locations of W4's evidence
---
Code smell: {{question}}
Finding: {{answer}}
Where: {{where|join:", "|or:"(none given)"}}
Is this a real problem in this PR, what does it cost, and can it be removed?
