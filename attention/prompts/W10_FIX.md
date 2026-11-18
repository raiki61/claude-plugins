---
vars:
  rung: text
  fix: text
  worldSolution: text
  ground: list   # "<leaf id> <location> :: <quote>"
---
Fix option ({{rung}}): {{fix}}
World's solution: {{worldSolution}}
It rests on these leaves' quotes:
{{ground|bullets}}
