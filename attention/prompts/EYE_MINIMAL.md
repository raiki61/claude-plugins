---
vars:
  purpose: text   # the purpose stage's sentence, or "(not available)"
  lines: text     # stage 0 line counts by file class
---
Changes the purpose does not need. Purpose of this PR: {{purpose}}
Added and deleted lines by file class (counted by the prep stage, for the size only): {{lines}}
List every change in this PR that the purpose does not need: a part, a file, an option, a check or a document that could go and leave the purpose met. Weigh each by how many places come to know the concept it adds, not by its line count. Start from the zero prescription: could the purpose be met by adding nothing there? Give the line count of each such change beside it.
